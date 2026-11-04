"""Object layer: business namespaces, collections, references and loaded objects."""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from operations import (
    GENERATED_MARKER,
    ROOT,
    Module,
    Operation,
    Param,
    docstring,
    identifier,
    member_names,
    pascal,
    product_class,
    snake,
    write,
)
from pydantic import BaseModel

PACKAGE = ROOT / "src" / "aioscaleway"
MAPPING = ROOT / "mapping.yaml"
COVERAGE = ROOT / "docs" / "coverage.md"
TREE = ROOT / "docs" / "objects.md"
LOCALITIES = ("zone", "region")
PAGING_PARAMS = {"page", "page_token"}
STANDARD_MEMBERS = {"update", "replace", "delete", "refresh"}
MODEL_ATTRIBUTES = {name for name in dir(BaseModel) if not name.startswith("__")}
RESERVED_MEMBERS = {"list", "dict", "set", "type", "str", "int", "float", "bool", "all"}
BUILTIN_NAMES = {
    "Any",
    "Literal",
    "Instant",
    "Money",
    "list",
    "dict",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "None",
}


IRREGULAR = {
    "aliases": "alias",
    "statuses": "status",
    "status": "status",
    "redis": "redis",
    "os": "os",
    "dns": "dns",
    "access": "access",
    "addresses": "address",
    "series": "series",
    "analytics": "analytics",
    "kafka": "kafka",
    "mongodb": "mongodb",
}


def singular(name: str) -> str:
    head, _, last = name.rpartition("_")
    if last in IRREGULAR:
        return f"{head}_{IRREGULAR[last]}" if head else IRREGULAR[last]
    for plural, single in (("ies", "y"), ("sses", "ss"), ("xes", "x"), ("ches", "ch")):
        if name.endswith(plural):
            return name[: -len(plural)] + single
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def version_rank(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v(\d+)(?:(alpha|beta)(\d*))?", version)
    if match is None:
        return (0, 0, 0)
    major, stage, number = match.groups()
    return (int(major), {"alpha": 0, "beta": 1, None: 2}[stage], int(number or 0))


@dataclass
class Call:
    operation: Operation
    module: Module
    api: str


@dataclass
class Resource:
    product: str
    module: Module
    segments: tuple[str, ...]
    parent: "Resource | None"
    locality: str | None = None
    listing_only: bool = False
    params: Counter[str] = field(default_factory=Counter)
    name: str = ""
    class_name: str = ""
    model: str | None = None
    summary: str | None = None
    load: Call | None = None
    listing: Call | None = None
    create: Call | None = None
    item_calls: dict[str, Call] = field(default_factory=dict)
    collection_calls: dict[str, Call] = field(default_factory=dict)
    listings: dict[str, Call] = field(default_factory=dict)
    children: list["Resource"] = field(default_factory=list)

    @property
    def param(self) -> str:
        return self.params.most_common(1)[0][0] if self.params else ""

    @property
    def key_names(self) -> list[str]:
        chain = [] if self.parent is None else self.parent.key_names
        return chain if self.listing_only else [*chain, self.param]

    @property
    def path(self) -> str:
        return f"{self.product}:{'/'.join(self.segments)}"


@dataclass
class NamespacePlan:
    name: str
    roots: list[Resource] = field(default_factory=list)
    calls: dict[str, Call] = field(default_factory=dict)
    listings: dict[str, Call] = field(default_factory=dict)
    modules: list[Module] = field(default_factory=list)


@dataclass
class Plan:
    namespaces: dict[str, NamespacePlan] = field(default_factory=dict)
    coverage: list[tuple[str, str, str]] = field(default_factory=list)


def parse_path(path: str) -> tuple[str | None, list[tuple[str, str]], list[str]]:
    segments = path.strip("/").split("/")[2:]
    locality = None
    if len(segments) >= 2 and segments[0] in ("zones", "regions"):
        locality = segments[1].strip("{}")
        segments = segments[2:]
    chain: list[tuple[str, str]] = []
    pending: list[str] = []
    for segment in segments:
        if segment.startswith("{"):
            name = "_".join(pending) or (chain[-1][0] if chain else "items")
            chain.append((snake(name), segment.strip("{}")))
            pending = []
        else:
            pending.append(snake(segment))
    return locality, chain, pending


def operation_words(operation: Operation) -> list[str]:
    return snake(operation.operation_id).split("_")


def member_name(
    operation: Operation, resource: Resource | None, mapping: dict[str, Any]
) -> str:
    words = operation_words(operation)
    if resource is None and words[0] == "list" and len(words) > 1:
        words = words[1:]
    if resource is not None:
        drop = set()
        for segment in resource.segments[-1:]:
            for word in segment.split("_"):
                drop |= {word, singular(word), word + "s"}
        kept = [word for word in words if word not in drop]
        words = kept if len(kept) > (1 if words[0] == "list" else 0) else words
        if words[0] == "list" and len(words) > 1:
            words = words[1:]
    name = identifier("_".join(words))
    key = f"{resource.path if resource else ''}:{name}"
    if key in mapping.get("members", {}):
        return str(mapping["members"][key])
    if name in STANDARD_MEMBERS or name in MODEL_ATTRIBUTES or name in RESERVED_MEMBERS:
        name = identifier(snake(operation.operation_id))
    return name


class Builder:
    def __init__(self, modules: list[Module], mapping: dict[str, Any]) -> None:
        self.modules = modules
        self.mapping = mapping
        self.plan = Plan()
        self.resources: dict[tuple[str, str, tuple[str, ...]], Resource] = {}

    def selected(self) -> list[tuple[Module, Any]]:
        by_api: dict[tuple[str, str], list[tuple[Module, Any]]] = defaultdict(list)
        for module in self.modules:
            for api in module.apis:
                by_api[(module.product, api.sub)].append((module, api))
        chosen = []
        for (product, sub), candidates in sorted(by_api.items()):
            if product in self.mapping.get("raw_only", {}):
                for module, api in candidates:
                    self.raw_only(
                        module,
                        api.operations,
                        "raw only: " + self.mapping["raw_only"][product],
                    )
                continue
            versions = self.mapping.get("versions", {})
            wanted = versions.get(f"{product}.{sub}", versions.get(product, "default"))
            ordered = sorted(candidates, key=lambda c: version_rank(c[0].version))
            stable = [c for c in ordered if version_rank(c[0].version)[1] == 2]
            pick = None
            if wanted == "default":
                pick = (stable or ordered)[-1]
            elif wanted is not None:
                pick = next(c for c in ordered if c[0].version == wanted)
            for module, api in candidates:
                if pick is not None and module is pick[0]:
                    chosen.append((module, api))
                else:
                    reason = "other version" if pick else "kept out by mapping.yaml"
                    self.raw_only(module, api.operations, reason)
        return chosen

    def raw_only(
        self, module: Module, operations: list[Operation], reason: str
    ) -> None:
        for operation in operations:
            self.plan.coverage.append(
                (f"{module.product}.{module.version}", operation.operation_id, reason)
            )

    def resource(
        self, module: Module, chain: list[tuple[str, str]], locality: str | None
    ) -> Resource:
        parent = None
        for depth in range(1, len(chain) + 1):
            segments = tuple(name for name, _ in chain[:depth])
            key = (module.product, module.version, segments)
            if key not in self.resources:
                self.resources[key] = Resource(module.product, module, segments, parent)
                if parent is not None:
                    parent.children.append(self.resources[key])
            current = self.resources[key]
            current.params[chain[depth - 1][1]] += 1
            current.locality = current.locality or locality
            parent = current
        assert parent is not None
        return parent

    def build(self) -> Plan:
        selected = self.selected()
        calls: list[tuple[Call, str | None, list[tuple[str, str]], list[str]]] = []
        for module, api in selected:
            for operation in api.operations:
                locality, chain, tail = parse_path(operation.path)
                call = Call(operation, module, api.name)
                if chain:
                    self.resource(module, chain, locality)
                calls.append((call, locality, chain, tail))
        collections = {(key[0], key[1], key[2]) for key in self.resources}
        self.adopted: dict[tuple[str, str, tuple[str, ...]], Resource] = {}
        for call, _, chain, tail in calls:
            operation = call.operation
            if not chain or len(tail) != 1 or operation.http_method != "GET":
                continue
            if not operation.operation_id.startswith("List"):
                continue
            module = call.module
            segments = (*[name for name, _ in chain], tail[0])
            root = self.resources.get((module.product, module.version, (tail[0],)))
            if (
                root is None
                or (module.product, module.version, segments) in self.resources
            ):
                continue
            parent = self.resources[
                (module.product, module.version, tuple(n for n, _ in chain))
            ]
            if root.parent is None and root is not parent and parent.parent is None:
                root.parent = parent
                parent.children.append(root)
                self.adopted[(module.product, module.version, segments)] = root
        for call, locality, chain, tail in calls:
            self.assign(call, locality, chain, tail, collections)
        self.name_resources()
        return self.plan

    def namespace(self, product: str) -> NamespacePlan:
        name = self.mapping["namespaces"].get(product)
        if name is None:
            raise SystemExit(f"mapping.yaml: no namespace for product {product}")
        if name not in self.plan.namespaces:
            self.plan.namespaces[name] = NamespacePlan(name)
        return self.plan.namespaces[name]

    def place(self, call: Call, where: str) -> None:
        module = call.module
        self.plan.coverage.append(
            (f"{module.product}.{module.version}", call.operation.operation_id, where)
        )

    def assign(
        self,
        call: Call,
        locality: str | None,
        chain: list[tuple[str, str]],
        tail: list[str],
        collections: set[tuple[str, str, tuple[str, ...]]],
    ) -> None:
        operation = call.operation
        module = call.module
        namespace = self.namespace(module.product)
        if module not in namespace.modules:
            namespace.modules.append(module)
        verb = operation.http_method
        is_list = operation.operation_id.startswith("List") and verb == "GET"
        owner = None
        if chain:
            owner = self.resources[
                (module.product, module.version, tuple(name for name, _ in chain))
            ]
        if not tail and owner is not None:
            needs_more = any(
                p.required and p.location != "path" and p.special is None
                for p in operation.params
            )
            if (
                verb == "GET"
                and owner.load is None
                and operation.operation_id.startswith("Get")
                and not needs_more
            ):
                owner.load = call
                self.place(call, f"await {owner.path}(...)")
                return
            standard = {"PATCH": "update", "DELETE": "delete"}.get(verb)
            if verb == "PUT":
                standard = (
                    "replace"
                    if operation.operation_id.startswith("Set")
                    else ("update" if "update" not in owner.item_calls else "replace")
                )
            if standard and standard not in owner.item_calls:
                owner.item_calls[standard] = call
                self.place(call, f"{owner.path}(...).{standard}()")
                return
            name = member_name(operation, owner, self.mapping)
            owner.item_calls[name] = call
            self.place(call, f"{owner.path}(...).{name}()")
            return
        segments = (*[name for name, _ in chain], "_".join(tail))
        target = self.resources.get(
            (module.product, module.version, segments)
        ) or self.adopted.get((module.product, module.version, segments))
        if target is not None:
            target.locality = target.locality or locality
            if is_list and target.listing is None:
                target.listing = call
                self.place(call, f"async for x in {target.path}")
                return
            if (
                verb == "POST"
                and target.create is None
                and operation.operation_id.startswith("Create")
            ):
                target.create = call
                self.place(call, f"{target.path}.create()")
                return
            name = member_name(operation, target, self.mapping)
            target.collection_calls[name] = call
            self.place(call, f"{target.path}.{name}()")
            return
        if is_list:
            name = member_name(operation, owner, self.mapping)
            segments = (*[name for name, _ in chain], name)
            key = (module.product, module.version, segments)
            if key in self.resources:
                segments = (*segments[:-1], identifier(snake(operation.operation_id)))
                key = (module.product, module.version, segments)
            listing = Resource(module.product, module, segments, owner, locality, True)
            listing.listing = call
            self.resources[key] = listing
            if owner is not None:
                owner.children.append(listing)
            self.place(call, f"async for x in {listing.path}")
            return
        if owner is not None:
            name = member_name(operation, owner, self.mapping)
            owner.item_calls[name] = call
            self.place(call, f"{owner.path}(...).{name}")
            return
        name = member_name(operation, None, self.mapping)
        if name in namespace.listings or name in namespace.calls:
            name = f"{module.product}_{name}"
        if is_list:
            namespace.listings[name] = call
        else:
            namespace.calls[name] = call
        self.place(call, f"{namespace.name}.{name}")

    def name_resources(self) -> None:
        for resource in self.resources.values():
            if resource.parent is None:
                self.namespace(resource.product).roots.append(resource)
            default = resource.segments[-1]
            resource.name = str(
                self.mapping.get("collections", {}).get(resource.path, default)
            )
            resource.class_name = str(
                self.mapping.get("classes", {}).get(resource.path, "")
            )
            resource.model = self.resource_model(resource)
            if resource.listing is not None and not resource.listing_only:
                item = list_item(resource.module.models, resource.listing.operation)
                if item != resource.model and item in resource.module.models:
                    resource.summary = item
        problems = []
        prefixes = self.mapping.get("prefixes", {})
        for namespace in self.plan.namespaces.values():
            counts = Counter(resource.name for resource in namespace.roots)
            explicit = self.mapping.get("collections", {})
            for resource in namespace.roots:
                if resource.path in explicit:
                    continue
                if counts[resource.name] > 1 and resource.product in prefixes:
                    resource.name = f"{prefixes[resource.product]}_{resource.name}"
            roots = Counter(resource.name for resource in namespace.roots)
            clashes = sorted(name for name, count in roots.items() if count > 1)
            for clash in clashes:
                owners = [r.path for r in namespace.roots if r.name == clash]
                problems.append(
                    f"{namespace.name}.{clash}: {', '.join(sorted(owners))}"
                )
        if problems:
            raise SystemExit(
                "Collections with the same name, rename them in mapping.yaml:\n  "
                + "\n  ".join(problems)
            )
        for namespace in self.plan.namespaces.values():
            everything = [
                r
                for r in self.resources.values()
                if self.namespace(r.product) is namespace
            ]
            short = Counter(pascal(singular(r.name)) for r in everything)
            for resource in everything:
                if resource.class_name:
                    continue
                base = pascal(singular(resource.name))
                if short[base] > 1 and resource.parent is not None:
                    base = pascal(singular(resource.parent.name)) + base
                resource.class_name = base
            names = Counter(r.class_name for r in everything)
            for resource in everything:
                if names[resource.class_name] > 1:
                    resource.class_name = (
                        product_class(resource.product) + resource.class_name
                    )
            names = Counter(r.class_name for r in everything)
            for resource in everything:
                if names[resource.class_name] > 1 and resource.listing_only:
                    resource.class_name += "Listing"
            names = Counter(r.class_name for r in everything)
            duplicates = sorted(name for name, count in names.items() if count > 1)
            if duplicates:
                raise SystemExit(
                    f"{namespace.name}: duplicate class names {duplicates}"
                )

    def resource_model(self, resource: Resource) -> str | None:
        if resource.listing_only:
            return None
        models = resource.module.models
        for call in (resource.load, resource.create):
            if call is None:
                continue
            model = unwrap(models, call.operation.response)
            if model is not None:
                return model
        if resource.listing is not None:
            item = list_item(models, resource.listing.operation)
            if item in models:
                return item
        return None


def is_identifier(param: Param) -> bool:
    """A string argument naming another resource: a reference or object is accepted too."""
    return (
        param.annotation in ("str", "str | None")
        and param.location != "path"
        and (param.wire.endswith("_id") or param.wire == "id")
        and param.special not in ("owner", "project_id", "organization_id")
    )


def unwrap(models: dict[str, Any], annotation: str | None) -> str | None:
    if annotation is None or annotation not in models:
        return None
    model = models[annotation]
    if annotation.endswith("Response"):
        typed = [
            f for f in model.fields if f.annotation.removesuffix(" | None") in models
        ]
        if len(model.fields) == 1 and len(typed) == 1:
            inner: str = typed[0].annotation.removesuffix(" | None")
            return inner
        return None
    return annotation


def list_item(models: dict[str, Any], operation: Operation) -> str | None:
    if operation.pagination is not None:
        return operation.pagination[1]
    response = models.get(operation.response or "")
    if response is None:
        return None
    lists = [
        f
        for f in response.fields
        if f.annotation.removesuffix(" | None").startswith("list[")
    ]
    if len(lists) != 1:
        return None
    item: str = lists[0].annotation.removesuffix(" | None")[5:-1]
    return item


def items_field(models: dict[str, Any], operation: Operation) -> str | None:
    if operation.pagination is not None:
        return None
    response = models.get(operation.response or "")
    if response is None:
        return None
    lists = [
        f
        for f in response.fields
        if f.annotation.removesuffix(" | None").startswith("list[")
    ]
    return lists[0].name if len(lists) == 1 else None


class Renderer:
    """Writes one namespace package: types.py, resources.py and __init__.py."""

    def __init__(
        self, plan: Plan, namespace: NamespacePlan, mapping: dict[str, Any]
    ) -> None:
        self.plan = plan
        self.namespace = namespace
        self.mapping = mapping
        self.public: dict[tuple[str, str], str] = {}
        self.resource_models: dict[tuple[str, str], Resource] = {}
        self.bound: dict[tuple[str, str], str] = {}
        self.imports: dict[str, set[str]] = defaultdict(set)
        self.apis: dict[str, tuple[Module, str]] = {}
        self.all_resources = self.collect()

    def collect(self) -> list[Resource]:
        found: list[Resource] = []

        def walk(resource: Resource) -> None:
            found.append(resource)
            for child in resource.children:
                walk(child)

        for root in self.namespace.roots:
            walk(root)
        for resource in found:
            if resource.model is not None:
                self.resource_models[(resource.module.product, resource.model)] = (
                    resource
                )
                self.bound[(resource.module.product, resource.model)] = (
                    resource.class_name
                )
            if resource.summary is not None:
                self.resource_models[(resource.module.product, resource.summary)] = (
                    resource
                )
                self.bound[(resource.module.product, resource.summary)] = (
                    f"{resource.class_name}Summary"
                )
        return found

    def type_names(self) -> dict[tuple[str, str], str]:
        names: dict[tuple[str, str], str] = {}
        counts: Counter[str] = Counter()
        for module in self.namespace.modules:
            for name in (*module.models, *module.enums, *module.aliases):
                if (module.product, name) not in self.resource_models:
                    counts[name] += 1
        resource_classes = {r.class_name for r in self.all_resources}
        for module in self.namespace.modules:
            for name in (*module.models, *module.enums, *module.aliases):
                if (module.product, name) in self.resource_models:
                    continue
                public = name
                if (
                    counts[name] > 1
                    or name in resource_classes
                    or name == namespace_class_name(self.namespace.name)
                ):
                    public = product_class(module.product) + name
                names[(module.product, name)] = public
        return names

    def rename(self, module: Module, annotation: str) -> str:
        def replace(match: re.Match[str]) -> str:
            word = match.group(0)
            if word in BUILTIN_NAMES:
                return word
            resource = self.resource_models.get((module.product, word))
            if resource is not None:
                alias = f"_{product_class(module.product)}{word}"
                self.imports[
                    f"aioscaleway._operations.{module.product}.{module.version}.models"
                ].add(f"{word} as {alias}")
                return alias
            public = self.public.get((module.product, word))
            if public is not None:
                self.imports[".types"].add(public)
                return public
            return word

        return re.sub(r"[A-Za-z_][A-Za-z0-9_]*", replace, annotation)

    def api_alias(self, call: Call) -> str:
        alias = "_" + re.sub(r"V\d+(Alpha|Beta)?\d*", "", call.api)
        module_path = (
            f"aioscaleway._operations.{call.module.product}.{call.module.version}.api"
        )
        self.imports[module_path].add(f"{call.api} as {alias}")
        return alias

    def render_types(self) -> str:
        self.public = self.type_names()
        lines = [GENERATED_MARKER]
        by_module: dict[str, list[str]] = defaultdict(list)
        for module in self.namespace.modules:
            path = f"aioscaleway._operations.{module.product}.{module.version}.models"
            for (product, name), public in sorted(self.public.items()):
                if product == module.product and (
                    name in module.models
                    or name in module.enums
                    or name in module.aliases
                ):
                    by_module[path].append(
                        name if name == public else f"{name} as {public}"
                    )
        exported = []
        for path, names in sorted(by_module.items()):
            lines.append(f"from {path} import (")
            lines += [f"    {name}," for name in sorted(names)]
            lines.append(")")
            exported += [name.split(" as ")[-1] for name in names]
        lines += ["", "__all__ = ["]
        lines += [f"    {name!r}," for name in sorted(exported)]
        lines.append("]")
        return "\n".join(lines) + "\n"

    def params(self, call: Call, skip: set[str]) -> list[Param]:
        return [
            p
            for p in call.operation.params
            if p.location != "path" and p.wire not in skip
        ]

    def signature(
        self, call: Call, params: list[Param], extra: list[str] | None = None
    ) -> list[str]:
        lines: list[str] = []
        ordered = sorted(params, key=lambda p: not p.required or p.special is not None)
        for param in ordered:
            annotation = self.rename(call.module, param.annotation)
            if is_identifier(param):
                annotation = "str | _Ref[Any]"
            if param.required and param.special is None:
                lines.append(f"{param.name}: {annotation}")
            else:
                if not annotation.endswith("| None") and annotation != "Any":
                    annotation += " | None"
                lines.append(f"{param.name}: {annotation} = None")
        return [*(extra or []), *lines]

    def doc(self, call: Call, indent: str = "        ") -> str:
        operation = call.operation
        preview = (
            None
            if version_rank(call.module.version)[1] == 2
            else "Preview: this operation is not generally available yet."
        )
        notes = "Deprecated by Scaleway." if operation.deprecated else None
        return docstring(
            operation.summary,
            operation.description
            if operation.description != operation.summary
            else None,
            preview,
            notes,
            indent=indent,
        ).rstrip("\n")

    def result(
        self, call: Call, expression: str, scope: str, owner: Resource | None = None
    ) -> tuple[str, str]:
        """The return annotation and statement of a method calling `call`."""
        module = call.module
        annotation = call.operation.response
        if annotation is None:
            return "None", f"        await {expression}"
        bound = self.owned(owner, module, annotation)
        if bound is not None:
            return (
                bound,
                f"        return {bound}._from(self._session, {scope}, await {expression})",
            )
        inner = unwrap(module.models, annotation)
        target_class = None if inner is None else self.owned(owner, module, inner)
        if inner is not None and target_class is not None:
            field_name = module.models[annotation].fields[0]
            optional = field_name.annotation.endswith("| None")
            lines = [
                f"        data = (await {expression}).{field_name.name}",
            ]
            if optional:
                lines.append(
                    "        return None if data is None else "
                    + f"{target_class}._from(self._session, {scope}, data)"
                )
                return f"{target_class} | None", "\n".join(lines)
            lines.append(
                f"        return {target_class}._from(self._session, {scope}, data)"
            )
            return target_class, "\n".join(lines)
        return self.rename(module, annotation), f"        return await {expression}"

    def owned(self, owner: Resource | None, module: Module, model: str) -> str | None:
        if owner is not None and owner.module is module:
            if model == owner.model:
                return owner.class_name
            if model == owner.summary:
                return f"{owner.class_name}Summary"
        return self.bound.get((module.product, model))

    @staticmethod
    def uncovered(call: Call, key: dict[str, str]) -> list[Param]:
        return [
            p
            for p in call.operation.params
            if p.location == "path"
            and p.wire not in key
            and p.special not in LOCALITIES
        ]

    def call_expression(
        self,
        call: Call,
        key: dict[str, str],
        params: list[Param],
        fixed: dict[str, str] | None = None,
    ) -> str:
        api = self.api_alias(call)
        arguments = []
        for param in call.operation.params:
            if param.location == "path" and param.wire in key:
                value = key[param.wire]
                if param.annotation == "int" and value.startswith("_required("):
                    value = f"int({value})"
                arguments.append(f"{param.name}={value}")
            elif param.location == "path" and param.special in LOCALITIES:
                arguments.append(f"{param.name}=None")
        for param in params:
            if fixed and param.wire in fixed:
                continue
            if is_identifier(param):
                value = f"_identifier({param.name})"
                if not param.required or param.special is not None:
                    value = f"None if {param.name} is None else {value}"
                arguments.append(f"{param.name}={value}")
                continue
            arguments.append(f"{param.name}={param.name}")
        for name, value in (fixed or {}).items():
            arguments.append(f"{name}={value}")
        return f"self._session.api({api}).{call.operation.method_name}({', '.join(arguments)})"

    def key_access(self, resource: Resource, call: Call, source: str) -> dict[str, str]:
        """Path parameter of `call` (wire name) to the expression reading it from `source`."""
        _, chain, tail = parse_path(call.operation.path)
        key: dict[str, str] = {}
        names = resource.key_names
        own = bool(chain) and not tail and chain[-1][0] == resource.segments[-1]
        if own or not chain:
            pairs = zip(reversed(chain), reversed(names), strict=False)
        else:
            pairs = zip(chain, names, strict=False)
        for (_, wire), canonical in pairs:
            key[wire] = f"_required({source}, {canonical!r})"
        for locality in LOCALITIES:
            key[locality] = f"{source}.get({locality!r})"
        return key

    def render_resource(self, resource: Resource) -> list[str]:
        if resource.listing_only:
            return self.render_collection(
                resource, "", None, f"{resource.class_name}Collection"
            )
        out: list[str] = []
        ref = f"{resource.class_name}Ref"
        loaded = resource.class_name if resource.model else None
        collection = f"{resource.class_name}Collection"
        model_alias = None
        if resource.model:
            model_alias = self.rename(resource.module, resource.model)

        target = repr(loaded) if loaded else "None"
        out += ["", "", f"class {ref}(_Ref[{target}]):"]
        out.append(
            f'    """A {singular(resource.name).replace("_", " ")} known by its identifier."""'
        )
        out.append("")
        out.append(f"    _id_name = {resource.param!r}")
        if resource.load is not None and loaded:
            key = self.key_access(resource, resource.load, "self._key")
            expression = self.call_expression(resource.load, key, [])
            annotation, statement = self.result(
                resource.load, expression, "self._key", resource
            )
            out += ["", f"    async def _load(self) -> {loaded}:"]
            if annotation == loaded:
                out.append(statement)
            else:
                out.append(
                    statement.replace(
                        "return None if data is None else ",
                        "assert data is not None\n        return ",
                    )
                )
        members: dict[str, list[str]] = {}
        for name, call in sorted(resource.item_calls.items()):
            members[name] = self.method(resource, name, call, "self._key", item=True)
        for name, call in sorted(resource.listings.items()):
            members[name] = self.listing_method(resource, name, call, "self._key")
        for child in resource.children:
            members[child.name] = [
                "",
                "    @property",
                f"    def {child.name}(self) -> {child.class_name}Collection:",
                f"        return {child.class_name}Collection(self._session, self._key)",
            ]
        fields = set()
        if resource.model:
            fields = {f.name for f in resource.module.models[resource.model].fields}
        for name in sorted(members):
            final = name if name not in fields else f"{name}_"
            out += [
                line.replace(f"def {name}(", f"def {final}(", 1)
                for line in members[name]
            ]
        if loaded and model_alias and resource.model:
            out += self.bound_class(
                resource, loaded, model_alias, resource.model, ref, "loaded"
            )
        if resource.summary:
            summary_alias = self.rename(resource.module, resource.summary)
            out += self.bound_class(
                resource,
                f"{resource.class_name}Summary",
                summary_alias,
                resource.summary,
                ref,
                "as listed, `await` it for every field",
            )
        out += self.render_collection(resource, ref, loaded, collection)
        return out

    def bound_class(
        self,
        resource: Resource,
        name: str,
        alias: str,
        model: str,
        ref: str,
        state: str,
    ) -> list[str]:
        out = ["", "", f"class {name}({alias}, {ref}):"]
        out.append(f'    """A {singular(resource.name).replace("_", " ")}, {state}."""')
        out += [
            "",
            "    @classmethod",
            f"    def _from(cls, session: _Session, scope: _Key, data: {alias}) -> Self:",
        ]
        out.append("        ref_key: _Key = {**scope}")
        out.append(
            f"        ref_key[{resource.param!r}] = {self.id_field(resource, model)}"
        )
        if resource.locality:
            out.append(
                f"        ref_key[{resource.locality!r}] = _text(getattr(data, {resource.locality!r}, None)) "
                f"or scope.get({resource.locality!r})"
            )
        out.append("        return _bind(cls, session, data, ref_key)")
        return out

    def collection_item(
        self, resource: Resource, loaded: str | None
    ) -> tuple[str, str]:
        """What iterating the collection yields, and how a listed item becomes it."""
        if resource.listing is None:
            return loaded or "Any", "data"
        listing = resource.listing
        listed = list_item(listing.module.models, listing.operation)
        if loaded and listed == resource.model:
            return loaded, f"{loaded}._from(self._session, self._scope, data)"
        if resource.summary and listed == resource.summary:
            summary = f"{resource.class_name}Summary"
            return summary, f"{summary}._from(self._session, self._scope, data)"
        if listed is None:
            return "Any", "data"
        return self.rename(listing.module, listed), "data"

    @staticmethod
    def integer_id(resource: Resource) -> bool:
        calls = [resource.load, *resource.item_calls.values()]
        for call in calls:
            if call is None:
                continue
            for param in call.operation.params:
                if param.location == "path" and param.wire == resource.param:
                    return param.annotation == "int"
        return False

    def id_field(self, resource: Resource, model: str) -> str:
        fields = {f.name for f in resource.module.models[model].fields}
        param = snake(resource.param)
        candidates = (
            param,
            "id" if param.endswith("_id") or param == "id" else "",
            param.removesuffix("_id"),
            "name",
        )
        for candidate in candidates:
            if candidate and candidate in fields:
                return f"_text(data.{candidate})"
        return f"scope.get({resource.param!r})"

    def render_collection(
        self, resource: Resource, ref: str, loaded: str | None, collection: str
    ) -> list[str]:
        item = self.collection_item(resource, loaded)[0]
        out = ["", "", f"class {collection}(_Collection[{item}]):"]
        locality = resource.locality
        if resource.listing_only:
            out.append(
                f'    """Every {singular(resource.name).replace("_", " ")}: iterate, or `filter`."""'
            )
            return out + self.render_listing(resource, item, collection, locality)
        out.append(
            f'    """Every {singular(resource.name).replace("_", " ")}: iterate, `filter`, or call with an identifier."""'
        )
        id_type = "int | str" if self.integer_id(resource) else "str"
        out += [
            "",
            f"    def __call__(self, {snake(resource.param)}: {id_type}, /"
            + (f", *, {locality}: str | None = None" if locality else "")
            + f") -> {ref}:",
        ]
        out.append(
            f"        ref_key: _Key = {{**self._scope, {resource.param!r}: _identifier({snake(resource.param)})}}"
        )
        if locality:
            out.append(
                f"        ref_key[{locality!r}] = {locality} or self._criteria.get({locality!r})"
            )
        out.append(f"        return {ref}._of(self._session, ref_key)")
        out += self.render_listing(resource, item, collection, locality)
        if resource.create is not None:
            out += self.method(
                resource, "create", resource.create, "self._scope", item=False
            )
        for name, call in sorted(resource.collection_calls.items()):
            out += self.method(resource, name, call, "self._scope", item=False)
        return out

    def render_listing(
        self, resource: Resource, item: str, collection: str, locality: str | None
    ) -> list[str]:
        out: list[str] = []
        if resource.listing is not None:
            listing = resource.listing
            params = [
                p for p in self.params(listing, set()) if p.wire not in PAGING_PARAMS
            ]
            extra = [f"{locality}: str | None = None"] if locality else []
            signature = self.signature(listing, params, extra)
            if signature:
                out += ["", "    def filter(", "        self,", "        *,"]
                out += [f"        {line}," for line in signature]
                out.append(f"    ) -> {collection}:")
                out.append(
                    '        """The same collection, narrowed to the items matching these criteria."""'
                )
                names = [p.name for p in params] + ([locality] if locality else [])
                out.append(
                    f"        return self._narrowed({', '.join(f'{n}={n}' for n in names)})"
                )
            out += self.items_method(
                resource, listing, None if resource.listing_only else item
            )
        return out

    def items_method(
        self, resource: Resource, listing: Call, loaded: str | None
    ) -> list[str]:
        key = (
            self.key_access(resource.parent, listing, "self._scope")
            if resource.parent
            else {}
        )
        for locality in LOCALITIES:
            key[locality] = f"self._criteria.get({locality!r})"
        api = self.api_alias(listing)
        arguments = []
        for param in listing.operation.params:
            if param.location == "path":
                value = key.get(param.wire, "None")
                if param.annotation == "int" and value.startswith("_required("):
                    value = f"int({value})"
                arguments.append(f"{param.name}={value}")
        criteria = (
            "**{k: v for k, v in self._criteria.items() if k not in "
            + repr(set(LOCALITIES))
            + "}"
        )
        arguments.append(criteria)
        models = listing.module.models
        method = listing.operation.method_name
        item, convert = self.collection_item(resource, loaded)
        out = ["", f"    async def _items(self) -> AsyncIterator[{item}]:"]
        if listing.operation.pagination is not None:
            out.append(
                f"        async for data in self._session.api({api}).{method}_iter({', '.join(arguments)}):"
            )
            out.append(f"            yield {convert}")
            out += self.pages_method(listing, api, method, arguments)
        else:
            field_name = items_field(models, listing.operation)
            out.append(
                f"        response = await self._session.api({api}).{method}({', '.join(arguments)})"
            )
            if field_name is None:
                out.append("        for data in [response]:")
            else:
                out.append(f"        for data in response.{field_name} or []:")
            out.append(f"            yield {convert}")
        return out

    def pages_method(
        self, listing: Call, api: str, method: str, arguments: list[str]
    ) -> list[str]:
        """Every page response, for the totals and sums an item does not carry."""
        assert listing.operation.pagination is not None
        items, _, total, _ = listing.operation.pagination
        page = self.rename(listing.module, listing.operation.response or "Any")
        out = ["", f"    async def pages(self) -> AsyncIterator[{page}]:"]
        out.append('        """Each page as the API returns it, totals and sums included."""')
        out.append("        number = 1")
        out.append("        seen = 0")
        out.append("        while True:")
        out.append(f"            response = await self._session.api({api}).{method}({', '.join(arguments)}, page=number)")
        out.append("            yield response")
        out.append(f"            seen += len(response.{items} or [])")
        stop = f"not response.{items}"
        if total:
            stop += f" or seen >= response.{total}"
        out.append(f"            if {stop}:")
        out.append("                return")
        out.append("            number += 1")
        return out

    def method(
        self, resource: Resource | None, name: str, call: Call, source: str, item: bool
    ) -> list[str]:
        key = self.key_access(resource, call, source) if resource else {}
        if not item:
            for locality in LOCALITIES:
                key[locality] = (
                    f"{locality} or self._criteria.get({locality!r})"
                    if resource
                    else locality
                )
        enum_param = next(
            (
                p
                for p in call.operation.params
                if p.wire == "action"
                and p.location == "body"
                and p.annotation in call.module.enums
                and call.operation.operation_id.endswith("Action")
            ),
            None,
        )
        if enum_param is not None:
            return self.enum_actions(resource, call, enum_param, key)
        params = self.params(call, set()) + self.uncovered(call, key)
        extra = []
        locality_params = [
            p.wire
            for p in call.operation.params
            if p.location == "path" and p.special in LOCALITIES
        ]
        if not item and locality_params:
            extra = [f"{locality_params[0]}: str | None = None"]
        expression = self.call_expression(call, key, params)
        scope = source if not item else source
        annotation, statement = self.result(call, expression, scope, resource)
        signature = self.signature(call, params, extra)
        out = ["", f"    async def {name}(", "        self,"]
        if signature:
            out.append("        *,")
            out += [f"        {line}," for line in signature]
        out.append(f"    ) -> {annotation}:")
        doc = self.doc(call)
        if doc:
            out.append(doc)
        out.append(statement)
        return out

    def enum_actions(
        self,
        resource: Resource | None,
        call: Call,
        enum_param: Param,
        key: dict[str, str],
    ) -> list[str]:
        module = call.module
        enum = module.enums[enum_param.annotation]
        enum_name = self.rename(module, enum.name)
        params = self.params(call, {"action"}) + self.uncovered(call, key)
        out: list[str] = []
        for member, value in zip(member_names(enum.values), enum.values, strict=True):
            if value.startswith("unknown"):
                continue
            name = identifier(self.mapping.get("words", {}).get(value, snake(value)))
            expression = self.call_expression(
                call, key, params, fixed={"action": f"{enum_name}.{member}"}
            )
            annotation, statement = self.result(call, expression, "self._key", resource)
            signature = self.signature(call, params)
            out += ["", f"    async def {name}(", "        self,"]
            if signature:
                out.append("        *,")
                out += [f"        {line}," for line in signature]
            out.append(f"    ) -> {annotation}:")
            out.append(f'        """Run the `{value}` action."""')
            out.append(statement)
        return out

    def listing_method(
        self, resource: Resource, name: str, call: Call, source: str
    ) -> list[str]:
        key = self.key_access(resource, call, source)
        params = self.params(call, set()) + self.uncovered(call, key)
        expression = self.call_expression(call, key, params)
        annotation, statement = self.result(call, expression, source, resource)
        out = ["", f"    async def {name}(", "        self,"]
        signature = self.signature(call, params)
        if signature:
            out.append("        *,")
            out += [f"        {line}," for line in signature]
        out.append(f"    ) -> {annotation}:")
        doc = self.doc(call)
        if doc:
            out.append(doc)
        out.append(statement)
        return out

    def render_resources(self) -> str:
        body: list[str] = []
        for resource in self.all_resources:
            body += self.render_resource(resource)
        namespace_class = namespace_class_name(self.namespace.name)
        body += ["", "", f"class {namespace_class}(_Namespace):"]
        body.append(f'    """The `{self.namespace.name}` business area."""')
        for root in sorted(self.namespace.roots, key=lambda r: r.name):
            body += [
                "",
                "    @cached_property",
                f"    def {root.name}(self) -> {root.class_name}Collection:",
            ]
            body.append(f"        return {root.class_name}Collection(self._session)")
        roots = {root.name for root in self.namespace.roots}
        prefixes = self.mapping.get("prefixes", {})
        for name, call in sorted(
            {**self.namespace.calls, **self.namespace.listings}.items()
        ):
            if name in roots:
                name = (
                    f"{prefixes.get(call.module.product, call.module.product)}_{name}"
                )
            body += self.method(None, name, call, "{}", item=False)
        header = [GENERATED_MARKER, "from __future__ import annotations", ""]
        header += [
            "from collections.abc import AsyncIterator",
            "from functools import cached_property",
            "from typing import Any, Literal, Self",
            "",
        ]
        header.append("from whenever import Instant")
        header.append("")
        header.append("from aioscaleway._models import Money")
        header.append(
            "from aioscaleway._objects import Collection as _Collection, Key as _Key, "
            "Namespace as _Namespace, Ref as _Ref, Session as _Session, bind as _bind, "
            "identifier as _identifier, required as _required, text as _text"
        )
        for path, names in sorted(self.imports.items()):
            if path == ".types":
                continue
            header.append(f"from {path} import (")
            header += [f"    {name}," for name in sorted(names)]
            header.append(")")
        if self.imports.get(".types"):
            header.append(f"from aioscaleway.{self.namespace.name}.types import (")
            header += [f"    {name}," for name in sorted(self.imports[".types"])]
            header.append(")")
        return "\n".join(header + body) + "\n"

    def render_init(self) -> str:
        names = []
        for resource in self.all_resources:
            names.append(f"{resource.class_name}Collection")
            if resource.listing_only:
                continue
            names.append(f"{resource.class_name}Ref")
            if resource.model:
                names.append(resource.class_name)
            if resource.summary:
                names.append(f"{resource.class_name}Summary")
        names.append(namespace_class_name(self.namespace.name))
        lines = [
            GENERATED_MARKER,
            f"from aioscaleway.{self.namespace.name}.resources import (",
        ]
        lines += [f"    {name}," for name in sorted(names)]
        lines += [")", "", "__all__ = ["]
        lines += [f"    {name!r}," for name in sorted(names)]
        lines.append("]")
        return "\n".join(lines) + "\n"


def namespace_class_name(name: str) -> str:
    return pascal(name) + "Namespace"


def render_namespaces(plan: Plan) -> str:
    lines = [
        GENERATED_MARKER,
        "from functools import cached_property",
        "from typing import TYPE_CHECKING",
        "",
    ]
    lines += ["from aioscaleway._objects import Session", "", "if TYPE_CHECKING:"]
    for name in sorted(plan.namespaces):
        lines.append(f"    from aioscaleway.{name} import {namespace_class_name(name)}")
    lines += ["", "", "class Namespaces:"]
    lines.append('    """Every business area, as an attribute of the client."""')
    lines += ["", "    _session: Session"]
    for name in sorted(plan.namespaces):
        cls = namespace_class_name(name)
        lines += ["", "    @cached_property", f'    def {name}(self) -> "{cls}":']
        lines.append(
            f"        from aioscaleway.{name} import {cls}  # lazy: an area is slow to import"
        )
        lines.append("")
        lines.append(f"        return {cls}(self._session)")
    return "\n".join(lines) + "\n"


def render_coverage(plan: Plan) -> str:
    lines = [
        "# Coverage",
        "",
        "Generated by scripts/generate.py: where every operation lives.",
        "",
    ]
    lines += ["| API | Operation | Object layer |", "|---|---|---|"]
    for api, operation, where in sorted(plan.coverage):
        lines.append(f"| {api} | {operation} | `{where}` |")
    return "\n".join(lines) + "\n"


def render_tree(plan: Plan) -> str:
    lines = [
        "# Object tree",
        "",
        "Generated by scripts/generate.py from specs/ and mapping.yaml.",
        "",
    ]

    def walk(resource: Resource, depth: int) -> None:
        indent = "  " * depth
        kind = "listing" if resource.listing_only else f"`{resource.class_name}`"
        members = sorted(
            [*resource.item_calls, *resource.listings, *resource.collection_calls]
            + (["create"] if resource.create else [])
        )
        detail = f" ({', '.join(members)})" if members else ""
        lines.append(
            f"{indent}- `{resource.name}`: {kind}, from `{resource.path}`{detail}"
        )
        for child in sorted(resource.children, key=lambda r: r.name):
            walk(child, depth + 1)

    for name, namespace in sorted(plan.namespaces.items()):
        lines += [f"## {name}", ""]
        for root in sorted(namespace.roots, key=lambda r: r.name):
            walk(root, 0)
        calls = sorted({**namespace.calls, **namespace.listings})
        if calls:
            lines.append(f"- methods: {', '.join(f'`{call}`' for call in calls)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def generate(modules: list[Module]) -> list[str]:
    mapping = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
    plan = Builder(modules, mapping).build()
    written = []
    for name, namespace in sorted(plan.namespaces.items()):
        renderer = Renderer(plan, namespace, mapping)
        base = PACKAGE / name
        write(base / "types.py", renderer.render_types())
        write(base / "resources.py", renderer.render_resources())
        write(base / "__init__.py", renderer.render_init())
        written.append(str(base))
    write(PACKAGE / "_namespaces.py", render_namespaces(plan))
    write(COVERAGE, render_coverage(plan))
    write(TREE, render_tree(plan))
    return written


def clean() -> None:
    for init in PACKAGE.glob("*/__init__.py"):
        if init.parent.name.startswith("_"):
            continue
        if init.read_text(encoding="utf-8").startswith(GENERATED_MARKER):
            for path in sorted(init.parent.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            init.parent.rmdir()


def remove(path: Path) -> None:
    if path.exists():
        path.unlink()

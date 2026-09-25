import json
import traceback
from collections.abc import Iterator, Mapping
from dataclasses import FrozenInstanceError
from io import BytesIO
from typing import cast
from urllib.request import Request
from uuid import UUID

import cairn_worker.feishu_credentials as credential_module
import pytest
from cairn_worker.feishu import FeishuDocumentClient
from cairn_worker.feishu_credentials import (
    FeishuCredentialFailure,
    FeishuCredentialResolver,
    FeishuCredentials,
)

ORG_A = UUID("11111111-1111-4111-8111-111111111111")
ORG_B = UUID("22222222-2222-4222-8222-222222222222")
ORG_C = UUID("33333333-3333-4333-8333-333333333333")
ENVIRONMENT_KEY = "CAIRN_FEISHU_CREDENTIALS_JSON"


def _registry(
    *,
    app_id_a: str = "app-alpha",
    app_secret_a: str = "secret-alpha",
    app_id_b: str = "app-bravo",
    app_secret_b: str = "secret-bravo",
) -> str:
    return json.dumps(
        {
            str(ORG_A): {
                "shared_alias": {"appId": app_id_a, "appSecret": app_secret_a}
            },
            str(ORG_B): {
                "shared_alias": {"appId": app_id_b, "appSecret": app_secret_b}
            },
        },
        separators=(",", ":"),
    )


def _assert_failure(
    raised: pytest.ExceptionInfo[FeishuCredentialFailure],
    code: str,
    *canaries: str,
) -> None:
    failure = raised.value
    assert failure.code == code
    assert failure.retryable is False
    assert failure.safe_detail
    rendered = f"{failure!r} {failure} {failure.args}"
    for canary in canaries:
        if canary:
            assert canary not in rendered


def test_same_alias_resolves_only_within_the_requested_organization() -> None:
    """Break caught: a global alias lookup could return another organization's secret."""
    resolver = FeishuCredentialResolver(_registry())

    first = resolver.resolve(org_id=ORG_A, credential_ref="shared_alias")
    second = resolver.resolve(org_id=ORG_B, credential_ref="shared_alias")

    assert first == FeishuCredentials(app_id="app-alpha", app_secret="secret-alpha")
    assert second == FeishuCredentials(app_id="app-bravo", app_secret="secret-bravo")
    with pytest.raises(FeishuCredentialFailure) as raised:
        resolver.resolve(org_id=ORG_C, credential_ref="shared_alias")
    _assert_failure(raised, "feishu_credentials_not_found", "shared_alias")


def test_credentials_are_frozen_and_diagnostics_hide_registry_values() -> None:
    """Break caught: routine diagnostics or mutation could expose or replace loaded secrets."""
    raw_json = _registry()
    resolver = FeishuCredentialResolver(raw_json)
    credentials = resolver.resolve(org_id=ORG_A, credential_ref="shared_alias")

    with pytest.raises(FrozenInstanceError):
        credentials.app_secret = "replacement"  # type: ignore[misc]
    rendered = f"{credentials!r} {resolver!r}"
    for canary in (raw_json, "app-alpha", "secret-alpha", "shared_alias"):
        assert canary not in rendered


class _TrackingEnvironment(Mapping[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        self._entries = values
        self.accessed: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.accessed.append(key)
        return self._entries[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def replace_exact_value(self, value: str) -> None:
        self._entries[ENVIRONMENT_KEY] = value


def test_environment_loading_reads_only_exact_variable_and_snapshots_its_value() -> None:
    """Break caught: aliases must not select other environment variables or change after loading."""
    original = _registry()
    environment = _TrackingEnvironment(
        {
            ENVIRONMENT_KEY: original,
            "shared_alias": "filesystem-or-variable-indirection-canary",
            "FEISHU_APP_SECRET": "global-fallback-canary",
        }
    )
    resolver = FeishuCredentialResolver.from_environment(environment)
    environment.replace_exact_value(_registry(
        app_id_a="mutated-app",
        app_secret_a="mutated-secret",
    ))

    credentials = resolver.resolve(org_id=ORG_A, credential_ref="shared_alias")

    assert credentials == FeishuCredentials(app_id="app-alpha", app_secret="secret-alpha")
    assert environment.accessed == [ENVIRONMENT_KEY]


def test_missing_environment_is_an_empty_optional_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: the optional connector must not become a Worker startup requirement."""
    monkeypatch.delenv(ENVIRONMENT_KEY, raising=False)
    resolver = FeishuCredentialResolver.from_environment()

    with pytest.raises(FeishuCredentialFailure) as raised:
        resolver.resolve(org_id=ORG_A, credential_ref="shared_alias")

    _assert_failure(raised, "feishu_credentials_not_found")


@pytest.mark.parametrize(
    ("org_id", "credential_ref"),
    [
        (str(ORG_A), "shared_alias"),
        (None, "shared_alias"),
        (ORG_A, None),
        (ORG_A, ""),
        (ORG_A, "1alias"),
        (ORG_A, "alias.with.dot"),
        (ORG_A, "a" * 65),
    ],
)
def test_invalid_lookup_arguments_are_indistinguishable_from_missing_bindings(
    org_id: object,
    credential_ref: object,
) -> None:
    """Break caught: invalid inputs must not reveal whether another scoped binding exists."""
    resolver = FeishuCredentialResolver(_registry())

    with pytest.raises(FeishuCredentialFailure) as raised:
        resolver.resolve(
            org_id=cast(UUID, org_id),
            credential_ref=cast(str, credential_ref),
        )

    _assert_failure(raised, "feishu_credentials_not_found", "shared_alias")


@pytest.mark.parametrize(
    "raw_json",
    [
        "",
        " ",
        "not-json-private-canary",
        "null",
        "[]",
        '"string"',
        "1",
        "true",
        "NaN",
        f'{{"{ORG_A}":null}}',
        f'{{"{ORG_A}":[]}}',
        f'{{"{ORG_A}":{{"shared_alias":null}}}}',
        f'{{"{ORG_A}":{{"shared_alias":[]}}}}',
        f'{{"{ORG_A}":{{"shared_alias":{{}}}}}}',
        f'{{"{ORG_A}":{{"shared_alias":{{"appId":"app"}}}}}}',
        (
            f'{{"{ORG_A}":{{"shared_alias":'
            '{"appId":"app","appSecret":"secret","extra":"rejected"}}}'
        ),
        f'{{"{ORG_A}":{{"shared_alias":{{"appId":1,"appSecret":"secret"}}}}}}',
        f'{{"{ORG_A}":{{"shared_alias":{{"appId":"app","appSecret":false}}}}}}',
        f'{{"{ORG_A}":{{"shared_alias":{{"appId":Infinity,"appSecret":"secret"}}}}}}',
    ],
)
def test_malformed_or_wrong_schema_configuration_fails_closed(raw_json: str) -> None:
    """Break caught: malformed JSON and type coercion must never create a usable binding."""
    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(
        raised,
        "feishu_credentials_invalid",
        "not-json-private-canary",
        "secret",
    )


@pytest.mark.parametrize(
    "raw_json",
    [
        f'{{"{ORG_A}":{{}},"{ORG_A}":{{}}}}',
        (
            f'{{"{ORG_A}":{{"shared_alias":{{"appId":"a","appSecret":"s"}},'
            '"shared_alias":{"appId":"b","appSecret":"t"}}}}'
        ),
        (
            f'{{"{ORG_A}":{{"shared_alias":'
            '{"appId":"a","appId":"b","appSecret":"s"}}}}'
        ),
    ],
)
def test_duplicate_json_keys_at_every_object_depth_are_rejected(raw_json: str) -> None:
    """Break caught: JSON last-key-wins behavior could silently replace a scoped secret."""
    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(raised, "feishu_credentials_invalid", "shared_alias")


@pytest.mark.parametrize(
    "organization_key",
    [
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        str(ORG_A).replace("-", ""),
        f" {ORG_A}",
    ],
)
def test_organization_keys_must_be_canonical_uuid_strings(organization_key: str) -> None:
    """Break caught: alternate UUID spellings could create ambiguous organization scopes."""
    raw_json = json.dumps(
        {organization_key: {"alias": {"appId": "app", "appSecret": "secret"}}}
    )

    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(raised, "feishu_credentials_invalid", organization_key)


@pytest.mark.parametrize(
    "alias",
    ["", "1alias", "alias.dot", "alias space", "é", "a" * 65],
)
def test_configuration_aliases_follow_the_exact_opaque_alias_grammar(alias: str) -> None:
    """Break caught: an alias must never become a path, environment name, or fuzzy key."""
    raw_json = json.dumps(
        {str(ORG_A): {alias: {"appId": "app", "appSecret": "secret"}}}
    )

    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(raised, "feishu_credentials_invalid", alias)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("appId", ""),
        ("appSecret", ""),
        ("appId", "   "),
        ("appSecret", "\t"),
        ("appId", "bad\x00value"),
        ("appSecret", "bad\nvalue"),
        ("appId", "\ud800"),
        ("appSecret", "\udfff"),
        ("appId", "x" * 4097),
        ("appSecret", "x" * 4097),
    ],
)
def test_credentials_reject_blank_control_surrogate_and_oversized_strings(
    field: str,
    value: str,
) -> None:
    """Break caught: unusable or unsafe credential text must fail before client creation."""
    credential = {"appId": "app", "appSecret": "secret", field: value}
    raw_json = json.dumps({str(ORG_A): {"alias": credential}})

    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(raised, "feishu_credentials_invalid", value)


@pytest.mark.parametrize(
    ("alias", "app_id", "app_secret"),
    [
        ("a", "i", "s"),
        ("a" * 64, "应用标识", "应用密钥"),
        ("maximum_credentials", "i" * 4096, "s" * 4096),
    ],
)
def test_valid_alias_and_credential_boundaries_reach_the_reader_client(
    alias: str,
    app_id: str,
    app_secret: str,
) -> None:
    """Break caught: inclusive valid boundaries must resolve and construct without networking."""
    resolver = FeishuCredentialResolver(
        json.dumps(
            {
                str(ORG_A): {
                    alias: {"appId": app_id, "appSecret": app_secret},
                }
            }
        )
    )

    assert resolver.resolve(org_id=ORG_A, credential_ref=alias) == FeishuCredentials(
        app_id=app_id,
        app_secret=app_secret,
    )
    client = resolver.create_client(org_id=ORG_A, credential_ref=alias)
    assert isinstance(client, FeishuDocumentClient)


def test_configuration_accepts_documented_empty_and_exact_resource_boundaries() -> None:
    """Break caught: inclusive limits and deliberately empty registries must remain usable."""
    FeishuCredentialResolver()
    FeishuCredentialResolver("{}")
    FeishuCredentialResolver(json.dumps({str(ORG_A): {}}))
    exact_mebibyte = "{}" + (" " * (1024 * 1024 - 2))
    FeishuCredentialResolver(exact_mebibyte)
    exact_credential = "x" * 4096
    resolver = FeishuCredentialResolver(
        json.dumps(
            {
                str(ORG_A): {
                    f"a{index}": {
                        "appId": exact_credential if index == 0 else "app",
                        "appSecret": "secret",
                    }
                    for index in range(256)
                }
            }
        )
    )

    assert resolver.resolve(org_id=ORG_A, credential_ref="a0").app_id == exact_credential
    assert resolver.resolve(org_id=ORG_A, credential_ref="a255").app_secret == "secret"


@pytest.mark.parametrize(
    "raw_json",
    [
        "{}" + (" " * (1024 * 1024 - 1)),
        json.dumps(
            {
                str(ORG_A): {
                    f"a{index}": {"appId": "app", "appSecret": "secret"}
                    for index in range(257)
                }
            }
        ),
        f'{{"{ORG_A}":{{"alias":{{"appId":' + ("[" * 1100) + "0" + ("]" * 1100),
    ],
)
def test_configuration_resource_limit_violations_fail_closed(raw_json: str) -> None:
    """Break caught: oversized, overpopulated, or excessively deep input must stay bounded."""
    with pytest.raises(FeishuCredentialFailure) as raised:
        FeishuCredentialResolver(raw_json)

    _assert_failure(raised, "feishu_credentials_invalid")


class _ExplodingEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        del key
        raise RuntimeError("environment-private-canary")

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def test_unexpected_parser_and_environment_errors_are_redacted_without_a_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: arbitrary boundary exceptions must not leak deployment data."""
    def unexpected_loads(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("parser-private-canary")

    monkeypatch.setattr(
        "cairn_worker.feishu_credentials.json.loads",
        unexpected_loads,
    )
    raw_json = '{"raw":"registry-private-canary"}'
    with pytest.raises(FeishuCredentialFailure) as parser_raised:
        FeishuCredentialResolver(raw_json)
    parser_traceback = "".join(
        traceback.format_exception(
            type(parser_raised.value),
            parser_raised.value,
            parser_raised.value.__traceback__,
        )
    )
    _assert_failure(
        parser_raised,
        "feishu_credentials_unexpected",
        "parser-private-canary",
        "registry-private-canary",
    )
    assert parser_raised.value.__cause__ is None
    assert parser_raised.value.__suppress_context__ is True
    assert "private-canary" not in parser_traceback

    monkeypatch.undo()
    with pytest.raises(FeishuCredentialFailure) as environment_raised:
        FeishuCredentialResolver.from_environment(_ExplodingEnvironment())
    environment_traceback = "".join(
        traceback.format_exception(
            type(environment_raised.value),
            environment_raised.value,
            environment_raised.value.__traceback__,
        )
    )
    _assert_failure(
        environment_raised,
        "feishu_credentials_unexpected",
        "environment-private-canary",
    )
    assert environment_raised.value.__cause__ is None
    assert environment_raised.value.__suppress_context__ is True
    assert "environment-private-canary" not in environment_traceback


def test_failed_resolution_does_not_construct_a_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: a missing scoped binding must fail before any client or transport exists."""
    called = False

    def forbidden_client(**_kwargs: str) -> FeishuDocumentClient:
        nonlocal called
        called = True
        raise AssertionError("client-private-canary")

    monkeypatch.setattr(credential_module, "FeishuDocumentClient", forbidden_client)
    resolver = FeishuCredentialResolver(_registry())

    with pytest.raises(FeishuCredentialFailure) as raised:
        resolver.create_client(org_id=ORG_C, credential_ref="shared_alias")

    _assert_failure(raised, "feishu_credentials_not_found", "client-private-canary")
    assert called is False


def test_client_factory_failures_are_redacted_and_interrupts_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: constructor failures must be safe without swallowing process interrupts."""
    resolver = FeishuCredentialResolver(_registry())

    def exploding_client(**_kwargs: str) -> FeishuDocumentClient:
        raise RuntimeError("factory-private-canary")

    monkeypatch.setattr(credential_module, "FeishuDocumentClient", exploding_client)
    with pytest.raises(FeishuCredentialFailure) as raised:
        resolver.create_client(org_id=ORG_A, credential_ref="shared_alias")
    rendered_traceback = "".join(
        traceback.format_exception(
            type(raised.value),
            raised.value,
            raised.value.__traceback__,
        )
    )
    _assert_failure(
        raised,
        "feishu_credentials_unexpected",
        "factory-private-canary",
        "shared_alias",
    )
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert "factory-private-canary" not in rendered_traceback

    def interrupted_client(**_kwargs: str) -> FeishuDocumentClient:
        raise SystemExit(23)

    monkeypatch.setattr(credential_module, "FeishuDocumentClient", interrupted_client)
    with pytest.raises(SystemExit, match="23"):
        resolver.create_client(org_id=ORG_A, credential_ref="shared_alias")


def test_parser_and_environment_keyboard_interrupts_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: credential loading must not convert process-control exceptions."""
    def interrupted_loads(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "cairn_worker.feishu_credentials.json.loads",
        interrupted_loads,
    )
    with pytest.raises(KeyboardInterrupt):
        FeishuCredentialResolver(_registry())

    monkeypatch.undo()

    class InterruptedEnvironment(_ExplodingEnvironment):
        def __getitem__(self, key: str) -> str:
            del key
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        FeishuCredentialResolver.from_environment(InterruptedEnvironment())


class _Response(BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.status = 200
        self.headers: dict[str, str] = {}


class _RecordingOpener:
    def __init__(self, token: str) -> None:
        self.requests: list[Request] = []
        self._responses = [
            _Response(
                json.dumps(
                    {"code": 0, "tenant_access_token": token, "expire": 7200}
                ).encode()
            ),
            _Response(
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "document": {
                                "document_id": "Doc123",
                                "revision_id": 1,
                                "title": "Scoped document",
                            }
                        },
                    }
                ).encode()
            ),
            _Response(json.dumps({"code": 0, "data": {"content": "body"}}).encode()),
            _Response(
                json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "document": {
                                "document_id": "Doc123",
                                "revision_id": 1,
                                "title": "Scoped document",
                            }
                        },
                    }
                ).encode()
            ),
        ]

    def open(self, request: Request, *, timeout: float) -> _Response:
        assert timeout == 10.0
        self.requests.append(request)
        return self._responses.pop(0)


def test_created_clients_send_scoped_credentials_and_never_share_token_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Break caught: client reuse could send one organization's secret or token for another."""
    constructed: list[tuple[str, str, _RecordingOpener]] = []

    def client_factory(*, app_id: str, app_secret: str) -> FeishuDocumentClient:
        opener = _RecordingOpener(f"token-{len(constructed)}")
        constructed.append((app_id, app_secret, opener))
        return FeishuDocumentClient(
            app_id=app_id,
            app_secret=app_secret,
            opener_factory=lambda *_handlers: opener,
        )

    monkeypatch.setattr(credential_module, "FeishuDocumentClient", client_factory)
    resolver = FeishuCredentialResolver(_registry())

    first = resolver.create_client(org_id=ORG_A, credential_ref="shared_alias")
    second = resolver.create_client(org_id=ORG_B, credential_ref="shared_alias")
    repeated = resolver.create_client(org_id=ORG_A, credential_ref="shared_alias")
    assert first is not second and first is not repeated and second is not repeated
    first.read_document("Doc123")
    second.read_document("Doc123")
    repeated.read_document("Doc123")

    assert [(app_id, secret) for app_id, secret, _opener in constructed] == [
        ("app-alpha", "secret-alpha"),
        ("app-bravo", "secret-bravo"),
        ("app-alpha", "secret-alpha"),
    ]
    assert [
        json.loads(cast(bytes, opener.requests[0].data)) for _app, _secret, opener in constructed
    ] == [
        {"app_id": "app-alpha", "app_secret": "secret-alpha"},
        {"app_id": "app-bravo", "app_secret": "secret-bravo"},
        {"app_id": "app-alpha", "app_secret": "secret-alpha"},
    ]
    for index, (_app_id, _secret, opener) in enumerate(constructed):
        assert [request.get_method() for request in opener.requests] == [
            "POST",
            "GET",
            "GET",
            "GET",
        ]
        assert all(
            request.get_header("Authorization") == f"Bearer token-{index}"
            for request in opener.requests[1:]
        )

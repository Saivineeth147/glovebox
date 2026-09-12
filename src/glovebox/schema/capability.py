"""The capability artifact: a typed, versioned, reviewable description of a recorded flow.

Design principles (see REPORT.md §2):

* **Decoupled from the transcript.** Nothing here references model messages. The recorder
  translates the model's ephemeral element references into `Target`s with several
  independent locator strategies computed from the live surface at action time.
* **A contract, not a step list.** `inputs`, `outputs`, `outcomes` and `success` are the
  parts a calling agent reads. `steps` are the parts the replay engine reads. A reviewer
  reads both.
* **Surface-agnostic vocabulary.** Targets are described by what a human perceives (role,
  accessible name, label, nearby text, position) so the same schema can be resolved by a
  DOM surface today and an accessibility-tree or screenshot surface tomorrow.
* **Three classes of non-happy-path.** `outcomes` (legitimate business results), `recoveries`
  (known interstitials / transient states with a scripted response) and `failure_signals`
  (stop now, surface a debuggable error). The replay engine never guesses which is which.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Literal["1.0"] = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- enums
class ActionKind(StrEnum):
    NAVIGATE = "navigate"  # go to a URL (template) — safe
    CLICK = "click"  # click a target — risk depends on what it does
    FILL = "fill"  # type into a field — reversible
    SELECT = "select"  # choose an option — reversible
    PRESS = "press"  # keyboard key (Enter, Escape) — reversible
    EXPECT_DIALOG = "expect_dialog"  # arm a handler for the next native dialog
    WAIT = "wait"  # wait for a condition — safe
    EXTRACT = "extract"  # read data into an output — safe
    ASSERT = "assert"  # checkpoint: verify conditions — safe


class RiskClass(StrEnum):
    READ = "read"  # observing only
    REVERSIBLE = "reversible"  # local UI state (typing, selecting, opening a form)
    IRREVERSIBLE = "irreversible"  # commits a business change (submit, confirm, delete)


class ConditionKind(StrEnum):
    TEXT_VISIBLE = "text_visible"  # substring/regex visible in the frame
    TEXT_ABSENT = "text_absent"
    ELEMENT_VISIBLE = "element_visible"  # a Target resolves and is visible
    URL_MATCHES = "url_matches"  # regex against the main frame or a named frame URL
    TITLE_MATCHES = "title_matches"
    DIALOG_OPEN = "dialog_open"  # a native dialog was raised
    HTTP_STATUS = "http_status"  # last navigation response status matched (e.g. 5xx)


class ParamType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


class ReviewStatus(StrEnum):
    DRAFT = "draft"  # recorded, not yet reviewed; unattended replay is refused
    APPROVED = "approved"  # a human reviewed it; agents may invoke it
    DEPRECATED = "deprecated"


# --------------------------------------------------------------------------- targeting
class TargetStrategy(_Strict):
    """One way of finding a control. Strategies are tried in order; each must resolve to
    exactly one visible element to be accepted (uniqueness is the safety check that turns
    'a locator matched' into 'the right control matched')."""

    kind: Literal[
        "role_name",  # accessible role + accessible name  (most stable, surface-agnostic)
        "label",  # visible label text associated with a field
        "text",  # exact visible text (links, buttons, cells)
        "name_attr",  # form control `name` attribute (legacy apps do have these)
        "near_text",  # first control of a role to the right of / below an anchor text
        "table_cell",  # cell at (row containing anchor text, column under header text)
        "css",  # structural CSS path (last resort, brittle by design)
        "bbox",  # normalized bounding box centre (screenshot/desktop surfaces)
    ]
    value: dict[str, Any]
    robustness: str = Field(description="Recorder's note on why/when this strategy holds.")


class Target(_Strict):
    description: str = Field(description="Human-readable name, e.g. 'Member No. input'.")
    frame: list[str] = Field(
        default_factory=list, description="Frame path from the top document by frame name."
    )
    strategies: list[TargetStrategy] = Field(min_length=1)

    @field_validator("strategies")
    @classmethod
    def _bbox_never_first(cls, v: list[TargetStrategy]) -> list[TargetStrategy]:
        if v and v[0].kind == "bbox" and len(v) > 1:
            raise ValueError("bbox must be a fallback strategy, never the primary one")
        return v


class Condition(_Strict):
    kind: ConditionKind
    value: str | None = Field(default=None, description="Text/regex/status per kind.")
    regex: bool = False
    target: Target | None = None
    frame: list[str] = Field(default_factory=list)
    timeout_ms: int = Field(default=5000, ge=0)

    def describe(self) -> str:
        if self.kind == ConditionKind.ELEMENT_VISIBLE and self.target:
            return f"{self.kind}: {self.target.description}"
        return f"{self.kind}: {self.value!r}"


class WaitSpec(_Strict):
    load_state: Literal["load", "domcontentloaded", "networkidle", "none"] = "load"
    settle_ms: int = Field(default=150, ge=0, description="Quiet time after load.")
    timeout_ms: int = Field(default=15000, ge=100)


# --------------------------------------------------------------------------- steps
class Step(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    action: ActionKind
    intent: str = Field(description="Why this step exists, in the operator's words.")
    target: Target | None = None
    value: str | None = Field(
        default=None,
        description="Literal or template. `{{ params.member_id }}` substitutes an input.",
    )
    wait: WaitSpec = Field(default_factory=WaitSpec)
    risk: RiskClass = RiskClass.REVERSIBLE
    expect: list[Condition] = Field(
        default_factory=list, description="Post-conditions; all must hold or the step fails."
    )
    extract_to: str | None = Field(default=None, description="Output name (EXTRACT only).")
    dialog_response: Literal["accept", "dismiss"] | None = Field(
        default=None, description="EXPECT_DIALOG only: how to answer the native dialog."
    )

    @model_validator(mode="after")
    def _shape(self) -> Step:
        needs_target = {ActionKind.CLICK, ActionKind.FILL, ActionKind.SELECT, ActionKind.EXTRACT}
        if self.action in needs_target and self.target is None:
            raise ValueError(f"step {self.id!r}: {self.action} requires a target")
        needs_value = {ActionKind.FILL, ActionKind.SELECT, ActionKind.NAVIGATE, ActionKind.PRESS}
        if self.action in needs_value and self.value is None:
            raise ValueError(f"step {self.id!r}: {self.action} requires a value")
        if self.action == ActionKind.EXTRACT and not self.extract_to:
            raise ValueError(f"step {self.id!r}: extract requires extract_to")
        if self.action == ActionKind.EXPECT_DIALOG and self.dialog_response is None:
            raise ValueError(f"step {self.id!r}: expect_dialog requires dialog_response")
        if self.action == ActionKind.ASSERT and not self.expect:
            raise ValueError(f"step {self.id!r}: assert requires at least one expectation")
        return self


# --------------------------------------------------------------------------- contract
class Parameter(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ParamType
    description: str
    required: bool = True
    default: str | int | float | bool | None = None
    pattern: str | None = Field(default=None, description="Regex the value must match.")
    enum: list[str] | None = None
    sensitive: bool = Field(
        default=False,
        description="Never persisted in logs, evidence or artifacts; only a hash is kept.",
    )
    example: str | None = None


class Extraction(_Strict):
    target: Target
    attribute: Literal["text", "value", "href"] = "text"
    regex: str | None = Field(default=None, description="Optional capture group 1 applied to text.")


class OutputSpec(_Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: ParamType
    description: str
    sensitive: bool = False


class Outcome(_Strict):
    """A legitimate business result that is not success and not a failure."""

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    description: str
    detect: Condition
    terminal: bool = True
    verified: bool = Field(
        default=False,
        description=(
            "The detector text was actually observed during discovery. An unverified detector "
            "is the model's guess at wording it never saw; it silently never fires, so the "
            "capability reports a hard failure where it promised a business outcome."
        ),
    )


class Recovery(_Strict):
    """A known exceptional state with a scripted, bounded response."""

    name: str
    detect: Condition
    actions: list[Step] = Field(default_factory=list)
    then: Literal["retry_step", "continue", "restart_capability", "escalate"] = "retry_step"
    max_attempts: int = Field(default=2, ge=1, le=5)


class AppRef(_Strict):
    app_id: str = Field(description="Vendor product identity shared across tenants.")
    vendor_version: str | None = None
    tenant: str | None = Field(default=None, description="Institution this was recorded on.")
    origin: str = Field(description="Scheme+host[:port] the flow runs against.")
    entry_path: str = Field(description="Path template of the first navigation.")


class Provenance(_Strict):
    discovery_run_id: str
    recorded_at: datetime
    model: str
    surface: str
    transcript_sha256: str = Field(description="Hash of the (redacted) transcript, not content.")
    recorded_by: str = "glovebox-recorder"


class ReviewState(_Strict):
    status: ReviewStatus = ReviewStatus.DRAFT
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None
    replays: int = 0
    replay_successes: int = 0

    @property
    def confidence(self) -> float | None:
        return None if self.replays == 0 else self.replay_successes / self.replays


class TenantOverride(_Strict):
    """Per-tenant specialisation of a shared capability. Applied by step id; only the
    listed fields change. This is how 'same vendor app, different institution' is handled
    without re-recording (REPORT.md §4)."""

    tenant: str
    origin: str | None = None
    entry_path: str | None = None
    step_targets: dict[str, Target] = Field(default_factory=dict)
    step_values: dict[str, str] = Field(default_factory=dict)
    extra_recoveries: list[Recovery] = Field(default_factory=list)
    notes: str | None = None


def shadowing_outcome(success: list[Condition], outcomes: list[Outcome]) -> str | None:
    """The code of a terminal outcome that would fire on the success screen, if any.

    Such an outcome ends the run before the extract steps execute, so the capability
    reports a business outcome and returns no outputs at all.
    """
    success_values = [c.value.lower() for c in success if c.value]
    for outcome in outcomes:
        detected = (outcome.detect.value or "").lower()
        if not (detected and outcome.terminal):
            continue
        if any(detected in value or value in detected for value in success_values):
            return outcome.code
    return None


class Capability(_Strict):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="Stable capability name.")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$", description="Semver of this artifact.")
    title: str
    description: str = Field(description="What it does, for a calling agent and a reviewer.")
    app: AppRef
    inputs: list[Parameter] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)
    success: list[Condition] = Field(
        min_length=1, description="Terminal checkpoint. All must hold for status=success."
    )
    outcomes: list[Outcome] = Field(default_factory=list)
    recoveries: list[Recovery] = Field(default_factory=list)
    failure_signals: list[Condition] = Field(
        default_factory=list,
        description="If any holds after a step, stop with a hard failure (app error page...).",
    )
    max_risk: RiskClass = Field(
        default=RiskClass.REVERSIBLE,
        description="Highest risk class this capability performs; policy checks it.",
    )
    provenance: Provenance
    review: ReviewState = Field(default_factory=ReviewState)
    overrides: list[TenantOverride] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ----------------------------------------------------------------- invariants
    @model_validator(mode="after")
    def _consistent(self) -> Capability:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        declared_outputs = {o.name for o in self.outputs}
        extracted = {s.extract_to for s in self.steps if s.extract_to}
        if missing := extracted - declared_outputs:
            raise ValueError(f"steps extract undeclared outputs: {sorted(missing)}")
        if unfilled := declared_outputs - extracted:
            raise ValueError(f"declared outputs never extracted: {sorted(unfilled)}")
        params = {p.name for p in self.inputs}
        for s in self.steps:
            for ref in _template_refs(s.value):
                if ref not in params:
                    raise ValueError(f"step {s.id!r} references unknown input {ref!r}")
        highest = max((s.risk for s in self.steps), key=_risk_rank)
        if _risk_rank(highest) > _risk_rank(self.max_risk):
            raise ValueError(
                f"max_risk={self.max_risk} but step risk reaches {highest}; declare it honestly"
            )
        for o in self.overrides:
            for sid in list(o.step_targets) + list(o.step_values):
                if sid not in ids:
                    raise ValueError(f"override for {o.tenant!r} names unknown step {sid!r}")
        if code := shadowing_outcome(self.success, self.outcomes):
            raise ValueError(
                f"terminal outcome {code!r} is detected by text that also appears in the "
                "success conditions; it would end the run on the success screen before "
                "outputs are extracted"
            )
        return self

    def for_tenant(self, tenant: str | None) -> Capability:
        """Return a copy with the tenant override applied (identity if none)."""
        if tenant is None or tenant == self.app.tenant:
            return self
        ov = next((o for o in self.overrides if o.tenant == tenant), None)
        if ov is None:
            raise KeyError(f"no override recorded for tenant {tenant!r}")
        steps = []
        for s in self.steps:
            data = s.model_dump()
            if s.id in ov.step_targets:
                data["target"] = ov.step_targets[s.id].model_dump()
            if s.id in ov.step_values:
                data["value"] = ov.step_values[s.id]
            steps.append(Step.model_validate(data))
        app = self.app.model_copy(
            update={
                "tenant": tenant,
                "origin": ov.origin or self.app.origin,
                "entry_path": ov.entry_path or self.app.entry_path,
            }
        )
        return self.model_copy(
            update={
                "steps": steps,
                "app": app,
                "recoveries": [*self.recoveries, *ov.extra_recoveries],
            }
        )

    def parameter(self, name: str) -> Parameter | None:
        return next((p for p in self.inputs if p.name == name), None)


def _risk_rank(r: RiskClass) -> int:
    return {RiskClass.READ: 0, RiskClass.REVERSIBLE: 1, RiskClass.IRREVERSIBLE: 2}[r]


def _template_refs(value: str | None) -> list[str]:
    import re

    if not value:
        return []
    return re.findall(r"\{\{\s*params\.([a-z][a-z0-9_]*)\s*\}\}", value)

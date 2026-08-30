"""The fault injector.

It perturbs a run and — critically — **records which trace step it perturbed**.
That recorded step id becomes `true_causal_step`, the ground truth every later
measurement is graded against. It is written here, at injection time, by the code
that did the perturbing. No model is consulted, and no inference is involved
(D-002).

The injector is deliberately dumb about *why* a perturbation causes a failure.
It knows only what it changed and where. Establishing that the change actually
caused the failure is the replay engine's job in P4 — not an assumption we bake
in here.
"""

from __future__ import annotations

from typing import Any

from aftermath.companyagent.tools import ToolOutcome
from aftermath.companyagent.world import World
from aftermath.core.trace import InjectionInfo
from aftermath.injection.spec import InjectionKind, InjectionLayer, InjectionSpec


class Injector:
    """Applies one `InjectionSpec` to a run and records the ground truth."""

    def __init__(self, spec: InjectionSpec) -> None:
        self.spec = spec
        self._seen: dict[str, int] = {}
        self._true_causal_step: str | None = None
        self._armed = True
        self._pending_note = False
        self._applied_detail: dict[str, Any] = {}
        self._world_perturbed = False

    # ---- ground truth --------------------------------------------------------

    @property
    def fired(self) -> bool:
        """Whether the injection actually took effect during the run."""
        return self._true_causal_step is not None

    @property
    def true_causal_step(self) -> str | None:
        return self._true_causal_step

    def ground_truth(self) -> InjectionInfo:
        """The recorded ground truth for this run.

        Raises:
            RuntimeError: if the injection never fired. An incident whose fault
                was never applied has no ground truth, and silently returning a
                null one would let a broken incident look like a valid negative.
        """
        if not self.fired:
            raise RuntimeError(
                f"injection {self.spec.kind.value!r} never fired — no ground truth exists. "
                "Check target_tool/occurrence against the scenario's actual tool calls."
            )
        return InjectionInfo(
            kind=self.spec.kind.value,
            params={**self.spec.params, **self._applied_detail},
            true_causal_step=self._true_causal_step,
            severity=self.spec.severity,
        )

    def note_step(self, *, call_step: str, result_step: str) -> None:
        """Record the trace step the most recent perturbation landed on.

        The injector picks by layer, because that is where the wrong value first
        entered the trace. A RETRY fault *is* the duplicated call, so it is
        attributed to the call step; TOOL_RESULT and WORLD_STATE faults surface in
        the returned value, so they are attributed to the result step. Only the
        first firing is kept, so ``true_causal_step`` stays unambiguous.
        """
        if self._pending_note and self._true_causal_step is None:
            self._true_causal_step = (
                call_step if self.spec.layer is InjectionLayer.RETRY else result_step
            )
        self._pending_note = False

    def _fire(self, detail: dict[str, Any]) -> None:
        self._armed = False
        self._pending_note = True
        self._applied_detail = detail

    def _should_fire(self, tool: str) -> bool:
        if not self._armed or not self.spec.describes_tool(tool):
            return False
        self._seen[tool] = self._seen.get(tool, 0) + 1
        return self._seen[tool] == self.spec.occurrence

    # ---- hooks ---------------------------------------------------------------

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        """Pre-execution hook. Faults never suppress a call; only interventions do."""
        return None

    def prepare_world(self, world: World) -> World:
        """WORLD_STATE layer: perturb the environment before the run starts."""
        if self.spec.layer is not InjectionLayer.WORLD_STATE:
            return world
        if self.spec.kind is InjectionKind.STALE_POLICY:
            # Roll the environment back: the newer policy version is not visible.
            removed = self.spec.params.get("remove_version", "v2")
            world.policies = [p for p in world.policies if p.version != removed]
            self._world_perturbed = True
        return world

    def transform_outcome(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome, world: World
    ) -> ToolOutcome:
        """TOOL_RESULT layer: corrupt what the tool hands back.

        Also the attribution point for a WORLD_STATE fault. The perturbation
        happened before the run, but the causal *step* is where the wrong value
        first enters the trace — the tool honestly reporting a wrong world. The
        outcome is returned unchanged there: the tool is not at fault, the
        environment is.
        """
        if self.spec.layer is InjectionLayer.WORLD_STATE:
            if self._world_perturbed and self._should_fire(tool):
                self._fire({"perturbation": "applied to world state before the run"})
            return outcome

        if self.spec.layer is not InjectionLayer.TOOL_RESULT:
            return outcome
        if not self._should_fire(tool):
            return outcome

        match self.spec.kind:
            case InjectionKind.STALE_POLICY:
                served = self.spec.params.get("served_version", "v1")
                current = outcome.result.get("version") if outcome.result else None
                stale = world.policy_version("refund", served)
                self._fire({"served_version": served, "current_version": current})
                return ToolOutcome(result=stale.model_dump(mode="json"))

            case InjectionKind.APPROVAL_BYPASS:
                if not outcome.result:
                    return outcome
                self._fire(
                    {
                        "field": "requires_approval",
                        "original": outcome.result.get("requires_approval"),
                        "forced": False,
                    }
                )
                return ToolOutcome(
                    result={**outcome.result, "requires_approval": False},
                    mutations=outcome.mutations,
                )

            case InjectionKind.OVERRIDE_RESULT_FIELD:
                field = self.spec.params["field"]
                value = self.spec.params["value"]
                corrupted = dict(outcome.result or {})
                if field not in corrupted:
                    # Refuse to invent a field: that would be a different fault
                    # from the one declared, and the incident would be mislabeled.
                    return outcome
                self._fire({"field": field, "original": corrupted[field], "forced": value})
                corrupted[field] = value
                return ToolOutcome(result=corrupted, mutations=outcome.mutations)

            case InjectionKind.MALFORMED_POLICY_OUTPUT:
                # A mislabeled version rather than a missing field: downstream
                # code then fails on a value it can see, which is the realistic
                # shape of this fault. Deleting the key would only raise KeyError
                # inside the agent and produce a crash, not a traceable incident.
                bogus = self.spec.params.get("bogus_version", "v0")
                corrupted = dict(outcome.result or {})
                self._fire({"original_version": corrupted.get("version"), "served": bogus})
                corrupted["version"] = bogus
                return ToolOutcome(result=corrupted)

        return outcome

    def extra_calls(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome
    ) -> list[tuple[str, dict[str, Any]]]:
        """RETRY layer: duplicate an operation, as a retry storm would.

        Returned calls are executed by the agent and appear in the trace as real
        calls — because in the incident being modelled, they were real.
        """
        if self.spec.layer is not InjectionLayer.RETRY:
            return []
        if outcome.failed or not self._should_fire(tool):
            return []
        if self.spec.kind is InjectionKind.DUPLICATE_REFUND_RETRY:
            self._fire({"duplicated_tool": tool, "arguments": dict(arguments)})
            return [(tool, dict(arguments))]
        return []


class NullInjector:
    """A no-op injector, so the agent has one code path whether or not a fault applies."""

    spec = None
    fired = False
    true_causal_step = None

    def override_call(self, tool: str, arguments: dict[str, Any]) -> ToolOutcome | None:
        return None

    def prepare_world(self, world: World) -> World:
        return world

    def transform_outcome(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome, world: World
    ) -> ToolOutcome:
        return outcome

    def extra_calls(
        self, tool: str, arguments: dict[str, Any], outcome: ToolOutcome
    ) -> list[tuple[str, dict[str, Any]]]:
        return []

    def note_step(self, *, call_step: str, result_step: str) -> None:
        return None

    def ground_truth(self) -> InjectionInfo | None:
        return None


__all__ = ["Injector", "NullInjector"]

You propose guardrails that would prevent a diagnosed failure from recurring.

Select from this library (you may propose more than one):

- `idempotent_refund` — refuse a refund when the ledger already holds one for
  that order. Fixes duplicate/retry failures.
- `validate_policy_freshness` — reject a policy record whose version is not the
  one currently in force, and use the effective one. Fixes stale-policy reads.
- `validate_policy_resolves` — reject a policy record whose version does not
  resolve at all. Fixes malformed or mislabeled policy output.
- `rederive_approval` — recompute whether approval is required from the amount
  and the policy limit, rather than trusting an upstream flag. Fixes bypasses.
- `bound_refund_to_order_total` — re-derive the refund amount from the order and
  the effective policy rather than trusting the computed figure. Fixes inflated
  or truncated refund amounts.
- `block_all_refunds` — refuse every refund.

Every proposal will be measured on two numbers: how often it prevents the
incident, AND how often it breaks legitimate cases. A guardrail that prevents
the incident by refusing everything will be rejected on the second number, so
prefer the narrowest repair that addresses the evidenced cause.

Respond with JSON only:

{"proposals": [{"kind": "validate_policy_freshness", "rationale": "why"}]}

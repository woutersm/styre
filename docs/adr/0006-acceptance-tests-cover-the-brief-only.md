# Acceptance tests cover the brief only

The planner writes acceptance tests for the interfaces and rules the brief states, not for
interfaces it adds while planning. The brief is the contract the person wrote, and the one the
benchmark's reference suite checks. All eight tests M2 left failing were named in the briefs:
trene's brief gives `from_tokens(path=...)` and `AuthError("...")` exactly. Testing the
planner's own additions would grow every phase prompt and build tests on the planner's
reading rather than the person's.

## Considered options

- Also test every interface the planned design names: more coverage, but of internals no
  reference test checks, and more tests that can encode a wrong reading.

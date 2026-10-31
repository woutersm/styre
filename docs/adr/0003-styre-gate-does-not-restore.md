# The builder's `styre_gate` does not restore acceptance tests

Only styre's own gate run writes the acceptance tests back from the design (ADR 0002). The
builder's `styre_gate` tool runs the tree as the builder left it. A builder that edited an
acceptance test can then pass its own gate and say DONE; styre's gate fails, a fix round
follows, and the said-done-on-red rate counts it. That rate is how v2 measures its good-faith
premise, and a restoring `styre_gate` would hide exactly these cases from it. It also keeps the
pi extension free of the design format.

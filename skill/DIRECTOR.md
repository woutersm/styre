# Directing styre

How an interactive assistant (the **director**) and the owner work with styre, which runs a
local model (the **builder**) unattended. Five rules; design craft is in
`writing-designs.md`.

1. **The owner decides what gets built.** The director and the owner write each design
   together; the owner approves it before it runs. The builder builds it through styre, and
   the gate decides when a phase is done.
2. **A design gives the builder every fact it needs** — files and line ranges, the signatures
   it calls, the traps already found — so it writes instead of researching. **Behaviour is
   checked by a program**: golden files from the old code for a port, tests for new work
   (the builder writes them; the director reads the tests, not the code). Never demand what
   nobody would notice.
3. **The director runs the runs.** It starts approved designs in order, and on a stop fixes
   the phase text — adds what the builder was hunting for, or splits the phase — and resumes,
   between phases, never under a running one. Stuck twice on the same work: the director
   writes that part itself and says so in the commit.
4. **One review per finished design**, new tests first; findings fixed with a test each.
   Then it is merged before the next design starts.
5. **The director asks before anything live**: merging, installing, deleting data,
   publishing — and before changing a design in a way the owner did not approve.

Frontend tests (Vitest + React Testing Library, introduced in P6 for
`RecommendationCard`) live co-located with their source files under
`frontend/src/` (e.g. `frontend/src/components/RecommendationCard.test.tsx`),
not in this directory - the standard convention for Vite/Vitest projects,
and it keeps a component and its test importing each other with a plain
relative path instead of reaching across the repo.

This directory is kept for parity with `tests/backend/` and as the place to
note that decision; run the suite from `frontend/`:

```
npm run test    # vitest run
npm run build   # tsc -b && vite build
npm run lint    # oxlint
```

All three are part of `scripts/dev_day_runner.py`'s baseline gate.

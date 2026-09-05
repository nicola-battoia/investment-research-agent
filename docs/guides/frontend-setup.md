# Frontend setup

The React SPA is already scaffolded. Use its checked-in package and lockfile;
do not run `create vite` or reinitialize shadcn.

1. Install Node.js 22+ and pnpm 11.18.0, matching
   [package.json](../../frontend/package.json).
2. Prepare [Supabase](supabase-setup.md) and start the
   [backend](backend-setup.md).
3. From the repository root:

```bash
cd frontend
pnpm install --frozen-lockfile
cp -n .env.example .env
# Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
# VITE_API_BASE_URL defaults to http://localhost:8000 in the example.
pnpm dev
```

Open the origin printed by Vite (normally [localhost:5173](http://localhost:5173)).
The backend's `ALLOWED_ORIGINS` must include that exact origin. Sign in with an
administrator-created email/password account.

Verify changes:

```bash
pnpm lint
pnpm build
```

The build type-checks the referenced projects with `tsc -b`. For type checking
alone, use `pnpm exec tsc -b`. The [frontend README](../../frontend/README.md)
contains the route/code map and manual browser checklist. Production uses
[Caddy](../../frontend/Caddyfile); Vite preview is only for local build inspection.

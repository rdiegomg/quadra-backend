# Deploy de QUADRA — producción a $0

Stack: **Supabase** (Postgres) + **Render** (API FastAPI, Docker) + **Vercel** (frontend Angular).

> Convención: `main` = desarrollo, `produccion` = lo desplegado. Render
> auto-despliega al pushear a `produccion`. La config vive en variables de
> entorno, no en código.

---

## 1. Postgres en Supabase (gratis)

1. Crear cuenta en https://supabase.com → **New project** → región más cercana.
2. En **Settings → Database → Connection string** copiar la URI
   **"Session pooler"** (puerto 5432, IPv4) — la directa es solo IPv6 y
   Render no siempre la alcanza.
3. Adaptar el driver: la URI viene como
   `postgresql://postgres.[ref]:PASS@aws-...pooler.supabase.com:5432/postgres`
   y hay que anteponerle `+psycopg`:
   `postgresql+psycopg://postgres.[ref]:PASS@aws-...pooler.supabase.com:5432/postgres`
4. **No correr seeds**: la base queda vacía. El arranque del contenedor
   corre `alembic upgrade head` + `scripts.seed_base` (solo rubros + admin).

## 2. Backend en Render (gratis)

1. Crear cuenta en https://render.com → **New → Web Service** → conectar el
   repo `quadra-backend`.
2. Runtime **Docker** (usa el `Dockerfile`/`render.yaml` del repo).
   Branch: `produccion`.
3. Variables de entorno:
   | Var | Valor |
   |---|---|
   | `DATABASE_URL` | URI de Supabase con `+psycopg` (paso 1.3) |
   | `SECRET_KEY` | string largo aleatorio (Render puede generarlo) |
   | `CORS_ORIGINS` | `https://<tu-app>.vercel.app` (se completa tras el paso 3) |
   | `ENVIRONMENT` | `production` |
   | `DEMO_AUTO_ACCEPT` | `false` |
   | `ADMIN_EMAIL` / `ADMIN_PASSWORD` | credenciales reales del admin |
4. Deploy → al levantar corre migraciones + seed base solo.
   Verificar `https://<api>.onrender.com/health` → `{"status":"ok"}`.
5. Anotar la URL pública, ej: `https://quadra-api.onrender.com`.

> Ojo: el plan free duerme tras ~15 min sin tráfico; la primera visita
> tarda ~30-60s en despertar. Es el precio de $0.

## 3. Frontend en Vercel (gratis)

1. En `quadra-frontend/src/environments/environment.ts` poner la URL real:
   `apiUrl: 'https://quadra-api.onrender.com/api'`
   → commit a `main`, merge a `produccion`.
2. Crear cuenta en https://vercel.com → **Add New → Project** → importar
   `quadra-frontend`. `vercel.json` ya configura build + rewrites (SPA).
3. Deploy → anotar `https://<app>.vercel.app`.
4. Volver a Render y setear `CORS_ORIGINS=https://<app>.vercel.app`
   → redeploy (Manual Deploy → Restart).

## 4. Verificación

- `https://<app>.vercel.app` → landing sin textos "demo".
- Registrar una empresa de prueba → login → dashboard vacío (sin datos).
- `https://<api>.onrender.com/docs` → endpoints OK.
- Login admin con las credenciales de `ADMIN_EMAIL`/`ADMIN_PASSWORD`.

## 5. Flujo de trabajo posterior

- Desarrollar en `main` (local: seed demo + `DEMO_AUTO_ACCEPT=true`).
- Para publicar: `git checkout produccion && git merge main && git push`
  en ambos repos → redeploy automático (Render) / manual (Vercel).

## Datos ficticios locales (no tocar en prod)

- `scripts.seed_demo` corre **solo en local**; nunca en producción.
- En prod la red arranca vacía: cada empresa se registra sola y las
  cadenas aparecen cuando hay obligaciones cruzadas reales.

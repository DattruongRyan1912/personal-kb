# CyberOS AI chat UI

Next.js (App Router, TypeScript, Tailwind, shadcn/ui) chat for the agent of `ai/backend` (epic #268). The answer
streams from `POST /api/v1/chat/stream` into the AI SDK's `useChat` through `src/lib/transport.ts`; a reload restores
the session from its transcript.

```sh
cp .env.example .env.local      # NEXT_PUBLIC_API_URL; Supabase keys, or NEXT_PUBLIC_DEV_LOGIN=1 locally
npm install
npm run dev                     # http://localhost:3001
```

The API must allow this origin (`CORS_ORIGINS=http://localhost:3001` in `ai/.env`). Without a Supabase project, set
`DEV_LOGIN=true` there (accepted only with a localhost `SUPABASE_URL`) and `NEXT_PUBLIC_DEV_LOGIN=1` here: the login
page then offers a dev sign-in.

Checks: `npm run lint && npm run typecheck && npm test && npm run build`.

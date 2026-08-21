/// <reference types="vite/client" />

// Environment variables read at build time. Declared explicitly so a typo in
// an import.meta.env key is a type error rather than a silent `undefined`.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

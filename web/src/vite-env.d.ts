/// <reference types="vite/client" />

// Vite resolves CSS imports in the bundle, so the types have to say the import is fine.
declare module "*.css";

// Vite turns a CSS import into a side effect. This file has no top-level
// import or export on purpose: a wildcard module declaration is only ambient
// in a script, and inside a module it would not apply project-wide.
declare module "*.css";

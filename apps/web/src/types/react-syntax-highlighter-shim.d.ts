declare module "react-syntax-highlighter/dist/esm/*" {
  // Wildcard shim for deep imports without their own types (components,
  // style objects and language definitions all share this declaration).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const value: any;
  export default value;
}

if (Number(process.versions.node.split('.')[0]) !== 22) {
  console.error(
    'Fieldwork requires Node 22. Use the version in .nvmrc. Node 24 caused a native build-exit crash on Windows during verification.',
  );
  process.exit(1);
}

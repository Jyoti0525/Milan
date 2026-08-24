# data/

Generated datasets land here. Nothing in this directory is committed.

Every dataset is a pure function of its seed, its difficulty tier and the
generator version, so committing the output would add megabytes to the
repository to store something one command reproduces exactly:

```bash
cd engine && uv run milan generate --seed 42 --difficulty realistic
```

`milan reproduce` regenerates a dataset and compares content hashes, which is
what makes "reproducible" a checked claim rather than an assertion.

# Tests

This directory contains the tests for the git bash functions.

## Running Tests

To run the tests, you'll first need to initialize the submodules:

```bash
git submodule update --init --recursive
```

Then, you can run the tests using bats:

```bash
./test/deps/bats-core/bin/bats test
```

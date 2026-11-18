<p align="center">
  <a href="https://github.com/lupaxa-developers-toolbox">
    <img src="https://raw.githubusercontent.com/the-lupaxa-project/brand-assets/master/logos/organisations/developers-toolbox/readme-logo.png" alt="Developers Toolbox" />
  </a>
</p>

<h1 align="center">Regexlab</h1>

Regex Lab is an offline workbench for regular expressions. It explains a
pattern from a syntax tree, runs it, generates examples, and compares
samples. It does not claim that two patterns are equivalent.

The PyPI name is `lupaxa-regexlab`. The import path is `lupaxa.regexlab`.
The console scripts are `regex-lab` and `regexlab`. Examples below use
`regex-lab`. `lupaxa` is a namespace package.

## Install

```bash
pip install lupaxa-regexlab
```

Requires Python 3.11+.

> **Note:** `python-regex` and `pcre2` are optional. If they are not
> installed, `regex-lab engines` says so. Regex Lab will not switch to
> another engine.
>
> **Note:** `NO_COLOR`, including an empty value, turns colour off.
> `--no-colour` does the same. Matches are then marked with `« »`.

With no arguments, a terminal opens the interactive workbench. A pipe
prints help and exits 2.

## What it Does

`regex-lab` parses the pattern before it runs it. Explain, lint, and the
diagrams read that tree. Matching, replacement, splitting, generation,
comparison, and benchmarks run in a worker process that can be killed on
timeout.

```bash
regex-lab explain '^(?P<name>[a-z]+)-(?P<id>\d+)$'
regex-lab parse '^(?P<name>[a-z]+)-(?P<id>\d+)$'
regex-lab test '^(?P<name>[a-z]+)-(?P<id>\d+)$' 'ab-12'
regex-lab generate '[ab]{2}' --count 3 --seed 1 --min-length 2 --max-length 2
regex-lab compare 'a+' 'b+' aaa bbb --fail-on-difference
regex-lab --version
```

`regexlab` accepts the same commands: `explain`, `parse`, `test`,
`interactive`, `matches`, `findall`, `replace`, `split`, `generate`,
`compare`, `analyse`, `lint`, `benchmark`, `visualise`, `escape`,
`suite`, `library`, `export`, `engines`, `flags`, `config`, and
`version`.

## Explain

```bash
regex-lab explain '^(?P<name>[a-z]+)-(?P<id>\d+)$'
```

```text
Start of the string.
Capture "name" as one or more lowercase letters.
A hyphen "-".
Capture "id" as one or more decimal digits.
End of the string.
```

`--detail summary` is one paragraph. `--detail technical` adds the engine,
flags, and offsets. `--flags a` describes `\d` as an ASCII digit.
`--flags m` describes `^` as the start of a line.

## Parse

Parse prints the tree and does not run the pattern.

```bash
regex-lab parse '^(?P<name>[a-z]+)-(?P<id>\d+)$'
```

```text
Expression
├── Start anchor
├── Named group: name
│   └── Character class: a-z
│       └── Repeat: one or more
├── Literal: -
├── Named group: id
│   └── Digit
│       └── Repeat: one or more
└── End anchor
```

An invalid pattern names the position and a fragment.

```bash
regex-lab parse '('
```

```text
error: Unclosed group. Expected ')'.
  position: 0
  fragment: (
```

That command exits 3.

## Test

The default mode is `fullmatch`. `matches` and `findall` default to
`finditer` unless you set `--mode`.

```bash
regex-lab test '^(?P<name>[a-z]+)-(?P<id>\d+)$' 'ab-12'
```

```text
subject: arg1
engine: python-re
flags: (none)
mode: fullmatch
matches: 1
highlighted: «ab-12»
match 1
  text: ab-12
  span: 0-5
  line: 1
  column: 1
  groups: ab, 12
  named: name=ab, id=12
pass
```

A miss exits 1.

```bash
regex-lab test '^[a-z]+$' 'AB'
```

```text
subject: arg1
engine: python-re
flags: (none)
mode: fullmatch
matches: 0
no match
fail: arg1
```

`replace` previews on stdout. It writes a file only with `--output`, or
with `--in-place --yes`. On `python-re`, write replacements as `\1` or
`\g<name>`. An unescaped `$1` is rejected.

## Generate and Compare

Generation checks every positive sample with the engine and mode. With
`--include-invalid`, each negative sample is checked the other way and
labelled.

```bash
regex-lab generate '[ab]{2}' --count 3 --seed 1 --min-length 2 --max-length 2 --include-invalid
```

```text
positive: aa
positive: ba
positive: bb
negative: wrong-character: Za
negative: truncated: a
negative: extra-character: aa!
negative: case-flip: Aa
```

The same `--seed` repeats the same samples. Backreferences, recursion,
conditionals, and lookaround are reported instead of skipped.

```bash
regex-lab compare 'a+' 'b+' aaa bbb --fail-on-difference
```

```text
both: 0
neither: 0
only first: 1
only second: 1
capture diffs: 0
span diffs: 0
replacement diffs: 0
Sample comparison only. This does not prove the patterns are equivalent.
```

That command exits 9 because `--fail-on-difference` was set.

## Engines

```bash
regex-lab engines
```

```text
Available
  python-re
Not installed
  python-regex
    pip install 'lupaxa-regexlab[regex]'
  pcre2
    pip install 'lupaxa-regexlab[pcre2]'
```

`python-re` is always available. The other two appear under Available
when their packages import.

```bash
regex-lab explain a --engine python-regex
```

```text
error: engine python-regex is not installed. pip install 'lupaxa-regexlab[regex]'. Regex Lab will not substitute another engine.
```

That command exits 7 when the `regex` package is absent.

## Flags

| Flag          | Default     | Meaning                                                   |
| ------------- | ----------- | --------------------------------------------------------- |
| `--engine`    | `python-re` | Engine name. A missing engine is an error.                |
| `--flags`     | (none)      | Letters such as `im`, or names such as `IGNORECASE`.      |
| `--mode`      | `fullmatch` | `search`, `match`, `fullmatch`, `finditer`, or `findall`. |
| `--json`      | off         | UTF-8 object with schema `1.0` and no colour codes.       |
| `--no-colour` | off         | Disable colour. A set `NO_COLOR` does the same.           |
| `--timeout`   | `1`         | Seconds before a match worker is stopped.                 |
| `--strict`    | off         | Unknown config keys fail. Lint warnings exit 10.          |
| `--seed`      | `0`         | Seed for generation and comparison.                       |
| `--config`    | user file   | Extra TOML file. Command-line options win.                |

`regex-lab flags` lists every letter. `regex-lab config` prints the
effective settings. Precedence is the command line, then `--config`, then
the user file, then the defaults.

```bash
regex-lab explain a --json
```

```json
{
  "schema_version": "1.0",
  "ok": true,
  "command": "explain",
  "engine": "python-re",
  "pattern": "a",
  "flags": "",
  "mode": "fullmatch",
  "error": null,
  "warnings": [],
  "explanation": "The literal 'a'.",
  "detail": "detailed"
}
```

## Regex Policy

Patterns are read as text. Suite files and config files are TOML, parsed
with `tomllib`, and never executed.

`python-re` is the default. Possessive quantifiers and atomic groups are
accepted there on Python 3.11 and newer. Property escapes, recursion, and
pattern-position `\g<name>` are rejected for that engine. Lookahead,
lookbehind, conditionals, and backreferences parse, and generation says
when it cannot expand them.

Replacement text follows the selected engine. Splits report segments and
separators. Escape uses that engine's escape function.

Lint reports findings and does not rewrite the pattern. `--strict` turns
a warning into exit 10. Analysis heuristics are labelled `heuristic`.

Benchmarks run in a separate process. A timeout is not mixed into the
average, and a hung worker is killed.

HTML and SVG diagrams escape the pattern. They do not load remote assets.

## Exit Codes

| Code | Result                                                         |
| ---- | -------------------------------------------------------------- |
| `0`  | Success, or a test and suite that passed.                      |
| `1`  | General failure, including a subject that missed `--expect`.   |
| `2`  | Bad arguments, unknown config keys, or no TTY for interactive. |
| `3`  | The pattern is not valid on the selected engine.               |
| `4`  | A suite assertion failed.                                      |
| `5`  | The match exceeded `--timeout`. The worker is killed.          |
| `6`  | An input or match limit was exceeded.                          |
| `7`  | Missing engine, or a construct that engine does not support.   |
| `8`  | Generation or comparison did not finish the requested sample.  |
| `9`  | Patterns differed and `--fail-on-difference` was set.          |
| `10` | Lint found a warning or error under `--strict`.                |

```bash
regex-lab version
```

```text
regex-lab 0.0.0
```

`regex-lab --version` prints the same line.

<a href="https://github.com/the-lupaxa-project">
  <img src="https://raw.githubusercontent.com/the-lupaxa-project/brand-assets/master/logos/components/footer-for-child-orgs.svg" alt="The Lupaxa Project Footer" width="100%" />
</a>

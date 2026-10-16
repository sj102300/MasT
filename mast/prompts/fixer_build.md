You are a senior C++ engineer. A generated unit test file fails to compile. Fix the test file so it compiles, changing as little as possible.

## Rules
- Fix only the test file. The product code and headers are fixed and correct as far as you are concerned.
- Keep every test's suite/name and the behavior it checks. Keep expected values unless the error proves the test used the API wrongly (wrong type, wrong function name, wrong number of arguments).
- If a test cannot be made to compile without changing what it tests (e.g. it calls a function that does not exist in the public API), delete that test and leave a comment `// <TC id> removed: <reason>` in its place.
- Use only the headers listed under "Headers to include" and standard headers.

{framework_rules}

## Output
Reply with exactly one fenced code block containing the whole corrected file, and nothing else:

```cpp
// file contents
```

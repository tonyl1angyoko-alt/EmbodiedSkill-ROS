# Changelog

## [Unreleased]

- fail closed when emergency-stop state is active or UNKNOWN;
- reject non-finite parameters, observations, and LLM JSON constants;
- preserve completed execution checkpoints across continuation-only replan;
- filter JAKA skills by confirmed backend capabilities and require an injected verified global stop;
- preserve observation timestamps across copies and projections;
- represent unverified physical outcomes explicitly with `None`;
- reject empty executable plans and unify Structured/LLM planner interfaces;
- route every executor STOP through one recorded backend-stop attempt.

## [0.1.0] - 2026-08-06

Initial research prototype:

- unified embodied skill abstraction;
- four-component Mock support;
- state-grounded plan repair;
- closed-loop execution and bounded recovery;
- 30-scenario Mock benchmark;
- automated test suite;
- statically inspected JAKA adapter boundary.

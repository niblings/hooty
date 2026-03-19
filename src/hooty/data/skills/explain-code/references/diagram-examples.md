# ASCII Diagram Examples

## Simple flow
```
start → validate → process → return
```

## Branching
```
       ┌─ yes → handle_success ─┐
check ─┤                         ├→ done
       └─ no  → handle_error  ──┘
```

## Loop
```
init → ┌→ condition? ─ no → exit
       │     │ yes
       │     ↓
       └── body
```

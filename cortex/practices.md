# Practices

## Do
- Write code a person can read top to bottom.
- One function, one job. The name says the job.
- Prefer a straight line of steps over clever helpers.
- If two functions or classes do the same thing, keep one and call it.
- Shorten a duplicate body to one return call.
- Keep parameters obvious. Avoid hidden shared state when a parameter will do.
- Explain the logic on the left in ordinary words when it changes.

## Do not
- Do not invent a second class or function that copies the first.
- Do not leave two identical logics in the same file.
- Do not write spaghetti that only a model can follow.
- Do not hide the real work in layers of wrappers.
- Do not ship a feature with no way to test it.
- Do not invent function names that are not already in the architecture note.

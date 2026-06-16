Sync the current branch with the latest master. Steps:

1. `git fetch origin master`
2. `git merge origin/master --no-edit`
3. If conflicts exist, check them with `git diff --name-only --diff-filter=U`
4. Resolve conflicts — the most common one is `app/main.py`: combine both sides' router imports into one sorted import block (don't drop any router from either side).
5. After resolving, run `ruff check . --fix && black .` to ensure the merge result is lint-clean.
6. Stage resolved files, commit the merge, and push.

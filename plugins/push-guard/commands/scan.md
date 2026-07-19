---
description: Scan the commits you have not pushed yet for secrets and not-ready work
argument-hint: "[BASE..HEAD]"
---

Scan the commits that a push would send, without pushing anything. Run exactly this
from the repository the user is working in, passing `$ARGUMENTS` through as an
explicit range when they gave one:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_push.py" ${ARGUMENTS:+--range "$ARGUMENTS"}
```

Exit codes: `2` a HIGH finding (a shaped credential, a credential file, a conflict
marker), `1` MEDIUM only (worth a look), `0` clean or nothing unpushed.

Report the findings to the user as the scanner printed them. If anything HIGH turned
up, say plainly that the secret has to come out of the commits themselves, since a
later commit does not remove it from history, and that a real credential should be
rotated regardless. Do not rewrite history, push, or edit files unless the user asks
you to.

A clean result means nothing matched a known credential shape. It is not proof the
diff holds no secret, and say so rather than calling the push safe.

#!/bin/bash
# unblock-git.sh — Recovers a broken git tree on the Raspberry Pi caused by
# tracked binary files (whatsflow.db + .wwebjs_auth) colliding with git stash pop.
#
# Safe to run multiple times. Preserves your local DB by backup.
#
# Usage:  cd /path/to/repo && sudo bash unblock-git.sh
set -e

REPO_DIR="$(pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="/tmp/whatsflow-backup-${STAMP}"

echo ">>> Repo: ${REPO_DIR}"
echo ">>> Backup dir: ${BACKUP_DIR}"
mkdir -p "${BACKUP_DIR}"

# ---------- 1. Backup local DB and WhatsApp session ----------
if [ -f backend/whatsflow.db ]; then
  echo ">>> Backing up backend/whatsflow.db"
  cp -f backend/whatsflow.db "${BACKUP_DIR}/whatsflow.db.bak"
fi
if [ -d whatsapp-service/.wwebjs_auth ]; then
  echo ">>> Backing up whatsapp-service/.wwebjs_auth"
  cp -r whatsapp-service/.wwebjs_auth "${BACKUP_DIR}/.wwebjs_auth.bak" || true
fi
if [ -d whatsapp-service/.wwebjs_cache ]; then
  cp -r whatsapp-service/.wwebjs_cache "${BACKUP_DIR}/.wwebjs_cache.bak" || true
fi

# ---------- 2. Abort any in-progress merge / rebase / stash pop ----------
echo ">>> Aborting any in-progress merge / rebase"
git merge --abort 2>/dev/null || true
git rebase --abort 2>/dev/null || true
git cherry-pick --abort 2>/dev/null || true

# ---------- 3. Clear conflicting stashed changes for binary files ----------
echo ">>> Resetting binary/session files to HEAD to clear conflicts"
git checkout -- backend/whatsflow.db 2>/dev/null || true
git rm -rf --cached backend/whatsflow.db 2>/dev/null || true
git rm -rf --cached whatsapp-service/.wwebjs_auth 2>/dev/null || true
git rm -rf --cached whatsapp-service/.wwebjs_cache 2>/dev/null || true
git rm -rf --cached whatsapp-service/node_modules 2>/dev/null || true

# ---------- 4. Reinforce .gitignore ----------
echo ">>> Reinforcing .gitignore"
touch .gitignore
for pat in \
  "backend/whatsflow.db" \
  "backend/whatsflow.db-journal" \
  "backend/whatsflow.db-wal" \
  "backend/whatsflow.db-shm" \
  "whatsapp-service/.wwebjs_auth/" \
  "whatsapp-service/.wwebjs_cache/" \
  "whatsapp-service/node_modules/" \
  "*.log"
do
  grep -qxF "$pat" .gitignore || echo "$pat" >> .gitignore
done

# ---------- 5. Nuke every local change and pull latest ----------
echo ">>> Stashing any remaining changes (safety net)"
git stash push -u -m "unblock-git-${STAMP}" 2>/dev/null || true

echo ">>> Hard resetting to origin/main"
git fetch origin
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git reset --hard "origin/${BRANCH}"
git clean -fd -e backend/whatsflow.db -e whatsapp-service/.wwebjs_auth -e whatsapp-service/.wwebjs_cache -e whatsapp-service/node_modules

# ---------- 6. Restore local DB from backup ----------
if [ -f "${BACKUP_DIR}/whatsflow.db.bak" ]; then
  echo ">>> Restoring backend/whatsflow.db from backup"
  cp -f "${BACKUP_DIR}/whatsflow.db.bak" backend/whatsflow.db
fi

# ---------- 7. Show status ----------
echo ""
echo ">>> DONE. Git status:"
git status
echo ""
echo ">>> Latest commits:"
git log --oneline -5
echo ""
echo ">>> Backup kept at: ${BACKUP_DIR}"
echo ">>> Now restart services:"
echo "    sudo systemctl restart whatsflow-backend whatsflow-whatsapp"

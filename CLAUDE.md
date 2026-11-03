# Projeto: edição de vídeo com Claude

Para editar vídeo use a skill **tiktok-editor** (`.claude/skills/tiktok-editor/SKILL.md`).
Ela orquestra as outras skills instaladas em `.claude/skills/`:

- `video-use` — edição por conversa (transcrição, EDL, cortes, grade, legendas). + `helpers/transcribe_local.py` (transcrição grátis offline).
- `remotion-*` — animações/motion graphics em React (títulos, CTA, gráficos).
- `hyperframes`, `hyperframes-cli`, `media-use`, `style-sampling`, `slideshow` — composição em HTML, assets, copiar estilo de vídeo de referência.

Vídeos brutos: `videos/<projeto>/`. Saídas: `videos/<projeto>/edit/`. Responder em PT-BR.
Sempre propor a estratégia e esperar confirmação antes de cortar.

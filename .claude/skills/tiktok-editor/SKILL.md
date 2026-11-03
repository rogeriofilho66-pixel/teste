---
name: tiktok-editor
description: Editor de vídeo curto (TikTok, Reels, Shorts) por conversa, em PT-BR. Pega vídeo bruto, corta silêncios e muletas, converte para 9:16, coloca legenda palavra-a-palavra estilo TikTok, normaliza o áudio em -14 LUFS e exporta. Use quando o usuário pedir para editar, cortar, legendar, “deixar pronto pro TikTok/Reels/Shorts”, fazer jump cut, reaproveitar vídeo horizontal ou montar vídeo de produto/TikTok Shop. Orquestra as skills video-use, remotion-* e hyperframes quando precisar de animação.
---

# Editor TikTok (PT-BR)

Camada por cima do **video-use** (edição por conversa) com o que faltava pra
vídeo curto brasileiro: funciona **sem chave de API**, já sai em 1080x1920,
legenda animada palavra-a-palavra e áudio no padrão das plataformas.

Script principal: `scripts/tiktok.py` (ao lado deste arquivo). Só precisa de
`ffmpeg` + Python 3.

## Fluxo (sempre nesta ordem)

1. **Inventário** — `python scripts/tiktok.py probe <video>` em cada arquivo.
   Ler `edit/project.md` se existir e resumir a última sessão em 1 frase.
2. **Transcrição** (escolha a primeira que funcionar):
   - `ELEVENLABS_API_KEY` presente → `python ../video-use/helpers/transcribe.py <video>` (melhor precisão).
   - Senão → `python ../video-use/helpers/transcribe_local.py <video> --language pt --model small` (grátis, local, mesmo formato JSON).
   - Sem nenhum dos dois → seguir sem transcrição: o autocut usa `silencedetect` e o vídeo sai **sem legenda** — avisar o usuário.
3. **Ler o material** — `pack_transcripts.py --edit-dir edit` → `takes_packed.md`.
   Apontar: gancho (primeiros 3 s), escorregões, repetições, melhor take.
4. **Propor a estratégia em 4–6 frases e ESPERAR o “ok”**:
   gancho escolhido · duração alvo · quanto cortar · estilo de legenda ·
   reframe (blur/crop) · se vai ter animação/CTA final.
5. **Executar** — caminho rápido:
   ```bash
   python scripts/tiktok.py pipeline <video> --transcript edit/transcripts/<nome>.json \
       --style hormozi --mode blur
   ```
   Caminho manual (multi-take, reordenar falas, overlays): escrever `edit/edl.json`
   seguindo o video-use e renderizar com `../video-use/helpers/render.py`; depois
   `tiktok.py reframe` + `tiktok.py captions --words edit/words_output.json`.
6. **Autoavaliação antes de mostrar** — extrair frames em 0.5 s, cada corte ±0.3 s e o
   último segundo; conferir legenda legível e fora da UI do app; medir
   `ffmpeg -i edit/final.mp4 -af ebur128 -f null -` (alvo −14 LUFS, pico ≤ −1 dBTP).
   Até 3 rodadas de correção; o que sobrar, avisar.
7. **Persistir** — acrescentar a sessão em `edit/project.md` (estratégia, decisões, pendências).

## Regras de vídeo curto (o que faz reter)

- **Gancho nos 1–3 s**: a primeira frase precisa ser a mais forte. Se o melhor
  gancho está no meio do vídeo, mover pro começo (EDL permite reordenar).
- **Sem respiro morto**: pausa máxima ~0.35 s (`--max-gap`). Conteúdo
  calmo/storytelling: 0.5 s.
- **Legenda**: 2–3 palavras por vez, MAIÚSCULA, palavra ativa destacada.
  Posição `--y 0.70` (acima da descrição/botões do TikTok). Nunca no terço de baixo
  nem na faixa direita (botões).
- **Muletas**: por padrão remove “é/éé/hã/hum”. `--aggressive` remove também
  “tipo/né/então/aí” — conferir se não quebrou o sentido.
- **Duração**: 15–35 s para venda/produto, 30–60 s para tutorial.
- **Final**: CTA claro (“segue pra parte 2”, “link no carrinho laranja”).
  Se o usuário quiser card animado, criar com remotion/hyperframes como overlay.
- **Áudio**: −14 LUFS integrado, −1 dBTP (o pipeline já faz).

## Estilos de legenda (`--style`)

| estilo   | visual                                       | quando usar                 |
|----------|----------------------------------------------|-----------------------------|
| hormozi  | branco, palavra ativa amarela, contorno grosso | padrão; fala direta, vendas |
| neon     | branco, palavra ativa verde neon             | tech, jogos, tom jovem       |
| clean    | branco, sem destaque, sombra suave           | estética, moda, lifestyle    |

## Reframe (`--mode`)

- `blur` (padrão): vídeo inteiro no centro + fundo desfocado. Seguro pra qualquer horizontal.
- `crop`: corta pro centro e preenche a tela. Use quando a pessoa/produto está centralizado.
- `fit`: barras pretas. Raramente.

## Animações e motion graphics

- Título, lower-third, CTA, contador, gráfico → **remotion-best-practices / remotion-create / remotion-render**.
- Recriar o estilo visual de um vídeo de referência → **style-sampling** e **hyperframes**.
- Cada animação é um overlay `.mp4` em `edit/animations/slot_<n>/`, aplicado
  **antes** da legenda (legenda sempre por último).

## Onde ficam os arquivos

```
videos/<projeto>/
├── <brutos, nunca alterados>
└── edit/
    ├── project.md          memória da edição
    ├── transcripts/*.json  cache da transcrição (não transcrever de novo)
    ├── takes_packed.md
    ├── edl.json            decisões de corte
    ├── words_output.json   palavras já no tempo do vídeo final
    ├── cut.mp4 → vertical.mp4 → captioned.mp4 → final.mp4
```

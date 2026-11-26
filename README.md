# stories-franciellifernandes

Robô que monta e publica os stories diários do Instagram @franciellifernandes.adv
(Direito Previdenciário). Mesmo código do robô do @dradasmultas; o que muda está em
`perfil.json` (temas, tom, estilo sóbrio, versículos do bom dia, busca no Migalhas) e em
`conhecimento.md` (regras do INSS que o robô pode afirmar).

- Fotos da Dra.: ficam **trancadas** em `fotos.enc.parte-*` (AES-256). O robô destranca com o
  segredo `FOTOS_CHAVE`. Na internet só aparecem os stories já publicados.
- Visual: foto escurecida, sombra preta, texto branco em Cormorant Garamond, assinatura FF.
- Testes: `python3 -m unittest discover -s testes -v`

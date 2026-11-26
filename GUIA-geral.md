# Stories automáticos do @dradasmultas: guia de configuração

Guia para a Dra. Francielli. Não precisa saber programar: são só cliques e copiar e colar.
A configuração é feita **uma vez** (cerca de 1 hora). Depois disso os stories são montados
e publicados sozinhos, todo dia, mesmo com o computador desligado.

---

## 1. Como funciona

**Todo dia, por volta das 19h**, um robô gratuito do GitHub (site que guarda arquivos e roda
programas na nuvem):

1. pede ao **Claude** (a inteligência artificial da Anthropic) para **buscar notícias de
   trânsito** dos últimos dias na internet (multas, CNH, Lei Seca, Detran, acidentes, carros);
2. abre e lê as matérias inteiras, escolhe o **tema do dia** (CNH suspensa, CNH cassada, multas irregulares ou Lei Seca, em
   rodízio) e escreve uma **sequência de 5 a 10 stories** com começo, meio e fim:
   bom dia que já anuncia o assunto → notícia resumida (2 stories) → explicação passo a passo → fechamento;
3. desenha os stories com cara de feitos no celular (fotos do Unsplash ou cores lisas, texto em
   etiquetas);
4. **manda tudo para o seu Telegram**. Você olha e responde **OK** (ou **OK menos 3**, ou **NÃO**).

**No dia seguinte**, entre 7h e 21h, outro robô publica os stories aprovados, um a um, nos
horários marcados. O que saiu fica anotado no `registro.csv`. Se der erro, chega e-mail.

```
 19h  notícias da web ─► Claude escreve a sequência ─► artes ─► Telegram: "OK?"
                                                                   │
 dia seguinte, 7h–21h  ◄── só o que você aprovou ──────────────────┘
         │
         ▼
  Instagram @dradasmultas  +  registro.csv  +  e-mail se der erro
```

### O que o robô respeita (já está nas instruções dele)
- Regras de trânsito só saem de uma **base conferida** (`conhecimento.md`), que você pode
  corrigir ou aumentar. O robô não inventa artigo, prazo nem valor.
- Regras da OAB: conteúdo informativo, sem promessa de resultado, sem preço, sem
  sensacionalismo, sem nome de vítima de acidente.
- Notícias resumidas com as palavras dele, só de matérias que ele realmente abriu e leu,
  sempre com o veículo e a data.

### A notícia vem resumida no próprio story
O robô **abre e lê a matéria inteira** no site do jornal e conta a notícia em **dois stories**:
o que aconteceu, e o que isso muda para quem dirige, sempre com o veículo e a data. Ninguém
precisa clicar em link. (Robôs não conseguem pôr a figurinha de link do Instagram; o link fica
só na mensagem do Telegram, para você conferir a fonte antes de aprovar.)

---

## 2. As opções que existem (e por que escolhi esta)

| Opção | Custo por mês | Monta os stories sozinho? | Observação |
|---|---|---|---|
| Meta Business Suite | grátis | ❌ | Você faz e agenda cada story na mão. |
| Agendadores pagos (mLabs, Etus…) | R$ 50 a 200 | ❌ | Só agendam o que você já fez. |
| **GitHub + Claude + API do Instagram** ✅ | **~US$ 5 a 15** (só o Claude) | ✅ busca notícia, escreve, desenha e publica | GitHub e Instagram são grátis. |

O custo do Claude é por uso: a busca de notícias e a escrita do dia ficam em torno de
**US$ 0,20 a 0,50 por dia**. Dá para pôr um limite de gasto no painel da Anthropic.

---

## 3. Passo a passo (você faz, eu acompanho)

> 🔒 **Segurança:** senhas, códigos e pagamentos quem digita é sempre você. Eu não crio contas,
> não aceito termos e não cadastro cartão por você. Nunca mande um token por WhatsApp ou e-mail:
> ele é como uma senha.

### Parte A: GitHub (10 min)
1. Crie uma conta gratuita em **github.com**.
2. **+** → **New repository** → nome `stories-dradasmultas` → **Public** → **Create repository**.
   *(Público é necessário para o Instagram conseguir buscar as imagens. Ali só ficam as artes
   dos stories, que vão ser públicas de qualquer jeito. Nunca coloque nada de cliente.)*
3. Me avise. **Com o seu OK**, eu subo os arquivos (ou te mostro como arrastar).
4. (Opcional) **Settings → Pages** → `main` e pasta `/docs` → **Save**: cria uma página com a lista
   das notícias já comentadas, se um dia você quiser pôr na bio.

### Parte B: o app e a chave na Meta
O app **Stories Doutora das Multas** já foi criado (id `1161944169703838`, portfólio Fernandes
Advocacia Trânsito, caso de uso "Gerenciar mensagens e conteúdo no Instagram"). Para apps novos a
Meta usa o **login unificado** com **token de usuário do sistema, que nunca expira**. Falta só
gerar a chave (o **token**), feito por você:

1. Abra **business.facebook.com** → portfólio **Fernandes Advocacia Trânsito** → **Configurações**
   (engrenagem) → **Usuários → Usuários do sistema** → **Adicionar**.
   Nome: `robo-stories`, função: **Administrador**.
2. Com o `robo-stories` selecionado → **Atribuir ativos**:
   - **Apps** → *Stories Doutora das Multas* → controle total;
   - **Contas do Instagram** → *@dradasmultas* → controle total (ou "Conteúdo").
3. Clique em **Gerar token** → app *Stories Doutora das Multas* → validade **Nunca** →
   marque **instagram_basic**, **instagram_content_publish** e **business_management** →
   **Gerar token**. Copie o código longo e guarde só até a Parte E (ele aparece uma vez só).

### Parte C: conta no Claude (10 min)
1. Entre em **console.anthropic.com** e crie a conta (termos e cartão: você decide e digita).
2. **Billing**: coloque crédito (US$ 10 dá para começar) e, se quiser, um limite mensal.
3. **API Keys → Create Key**, nome `stories-dradasmultas`. Copie a chave (guarde até a Parte E).

### Parte D: robô no Telegram para aprovar (5 min)
1. No Telegram, abra a conversa com **@BotFather** → `/newbot` → dê um nome (ex.: *Stories
   Doutora das Multas*) e um usuário terminado em `bot`. Ele responde com um **token**: copie.
2. Abra a conversa com o seu robô novo e mande **oi**.
3. Me avise: eu te mostro como descobrir o número da sua conversa (o **chat id**).

### Parte E: guardar as chaves no GitHub (5 min)
No repositório: **Settings → Secrets and variables → Actions → New repository secret**.
Crie um por um (nome exatamente assim):

| Nome | O que colar |
|---|---|
| `IG_TOKEN` | token da Meta (Parte B) |
| `IG_USER_ID` | `17841472104337280` (o número da @dradasmultas) |
| `ANTHROPIC_API_KEY` | chave do Claude (Parte C) |
| `TELEGRAM_BOT_TOKEN` | token do BotFather (Parte D) |
| `TELEGRAM_CHAT_ID` | número da conversa (Parte D) |

Na aba **Variables** (mesma tela):

| Nome | Valor | Para quê |
|---|---|---|
| `API_HOST` | `graph.facebook.com` | **obrigatório**: diz ao robô para usar o login unificado |
| `STORIES_POR_DIA` | de `5` a `10` (padrão 7) | quantos stories por dia |
| `APROVACAO` | `obrigatoria` (padrão) ou `automatica` | `automatica` publica sem pedir OK |

Como o token de usuário do sistema **não vence**, não é preciso renovar nada.

### Parte F: testes, do mais seguro ao real
Na aba **Actions** (se pedir, clique em *I understand… enable them*):

1. **Gerar stories do dia seguinte → Run workflow** com **"Usar textos de exemplo"** marcado.
   Não gasta nada. Confere se as artes aparecem na pasta `stories/` e se chegam no Telegram.
   *(Depois desse teste eu apago o dia de exemplo da fila.)*
2. **Publicar stories → Run workflow → verificar-token**: ✅ verde e `Token OK. Conta:
   @dradasmultas` = a chave da Meta funciona. Nada é publicado.
3. **Gerar stories do dia seguinte → Run workflow** sem marcar exemplo: primeira sequência de
   verdade, feita pelo Claude (custa centavos). Você confere no Telegram.
4. **Só com o seu OK:** responda **OK** no Telegram. No dia seguinte os stories começam a sair.
   Para ver um saindo na hora: **Publicar stories → publicar-um** com o nome do arquivo.

---

## 4. Os destaques

As artes no visual dos carrosséis ficam para os **destaques**, prontas na pasta
`stories/destaques/` (cada tema com a capa e a sequência):

| Destaque | Stories | Conteúdo |
|---|---|---|
| **LEI SECA** | 6 | "Fui pego no bafômetro. E agora?": o que acontece na hora, recusa, suspensão com defesa, reincidência, o que fazer |
| **CNH SUSPENSA** | 5 | o que é, por que acontece, por quanto tempo, como voltar a dirigir, cuidado com a cassação |
| **CNH CASSADA** | 5 | diferença para suspensa, quando acontece, 2 anos, comparativo, defesa |
| **MULTA COM ERRO** | 5 | o que o auto precisa trazer, notificação atrasada, radar, o que conferir |
| **MULTAS** | 7 | prazo, mito da multa paga, valores, pontos, notificação, celular, indicação de condutor |

**Como montar (pelo celular, uma vez):** o Instagram não deixa robô criar destaque.
1. Publique a sequência do tema como stories normais. Pelo celular é o mais simples; ou o robô
   publica com **publicar-um** (ex.: `destaques/lei-seca/01.jpg`).
2. No perfil: **+ Novo** (destaques) → selecione os stories do tema → nome (ex.: *Lei Seca*).
3. **Editar capa** → ícone de galeria → escolha a `capa.jpg` do tema (salve no celular antes).

---

## 5. No dia a dia

- **Modo atual: automático** (variável `APROVACAO` = `automatica`). Às ~19h chegam no Telegram as
  artes do dia seguinte só para você ver. Elas saem sozinhas. Para cancelar algum, responda
  `NÃO 3` (tira o 3) ou `NÃO` (cancela o dia). Para voltar a exigir aprovação, troque a variável
  para `obrigatoria`: aí só sai o que você responder `OK`.
- **Corrigir uma regra:** edite o `conhecimento.md`. O robô passa a usar a versão nova no
  próximo dia.
- **Ver o que saiu:** `registro.csv` (`publicado`, `erro` ou `pulado-atrasado`).
- **Story extra feito por você:** suba o .jpg (em pé, 1080 × 1920) na pasta `stories/` e
  acrescente uma linha na `fila.csv`: `meu-story.jpg,08/12/2026,10:00,aprovado,`
- **Horários:** os stories saem entre 7h e 21h, espalhados. O robô passa a cada 30 minutos,
  então um story das 9:20 sai entre 9:37 e ~10:10.
- **Imagens antigas** são apagadas da pasta depois de 21 dias (já estão no arquivo do Instagram).

**Atenção:** o GitHub desliga robôs de repositórios **60 dias sem alteração**. Como o robô
grava algo todo dia, isso só acontece se tudo ficar parado. Para religar: Actions → escolher o
robô → **Enable workflow**.

---

## 6. Limites honestos
- Stories pelo robô saem **sem figurinhas** (link, enquete, pergunta, música).
- O Claude pode errar. Por isso a aprovação vem **ligada por padrão**: troque para
  `automatica` só quando estiver confiante com a qualidade.
- Limite da Meta: 25 publicações por robô a cada 24h (usamos até 10).
- Se a Meta um dia revogar o token (por exemplo, se o usuário do sistema for apagado), chega
  e-mail de erro: é só gerar outro na Parte B e trocar o `IG_TOKEN`.

---

## 7. Story a partir de uma foto sua (pelo Telegram)

Mande a foto para o robô do Telegram do perfil (academia, café, escritório...). Para melhor
qualidade, mande como **arquivo** (clipe → Arquivo). Junto, se quiser, escreva instruções:

| Você escreve | O robô faz |
|---|---|
| `"segunda começando com café"` (entre aspas) | usa exatamente esse texto |
| nada | o Claude olha a foto e escreve uma frase curta e elegante |
| `sem texto` | só a foto com a logo FF |
| `sem sombra` | tira a sombra preta atrás das letras |
| `sem escurecer` / `mais escuro` | muda a exposição da foto |
| `em cima` / `no meio` / `embaixo` | posição do texto |
| `com faixa` | fundo escuro atrás das letras, como no Instagram |
| `agora` / `às 18h` | quando publicar (sem pedido: próximo horário livre do dia) |

Em até 30 minutos ele responde com a prévia e o horário. Para desistir, responda `CANCELAR`.

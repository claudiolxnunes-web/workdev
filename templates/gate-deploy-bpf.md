# Gate de deploy — BPF Consult

Adaptado do `full-release-alignment gate` do `release-process.md`. A ideia central
do original: **um release não está completo quando só a tag existe**. Tudo precisa
apontar para o mesmo commit, e as superfícies públicas precisam ser lidas de volta.

Aqui isso vira: código, serviço, roteamento e domínio precisam concordar.

## Pré-condições

- Árvore de trabalho limpa (`git status --porcelain` vazio).
- Local igual ao remoto: `git rev-list --left-right --count main...origin/main` retorna `0 0`.
- Você sabe qual serviço systemd e qual porta o app usa.

## As 6 provas

Rode uma por vez. Qualquer falha interrompe — não siga para a próxima.

**1. Commit exato**

```bash
git rev-parse HEAD
```

Anote. É esse SHA que todas as provas seguintes precisam refletir.

**2. Build reproduzível**

Rode o build duas vezes. A segunda não pode produzir diferença:

```bash
npm run build && git status --porcelain
```

Saída vazia. Se sujar, o build grava artefato versionado — corrija o `.gitignore`
ou o gerador antes de continuar.

**3. Serviço ativo e recente**

```bash
systemctl is-active <serviço> && systemctl show -p ActiveEnterTimestamp <serviço>
```

O timestamp precisa ser posterior ao deploy. Serviço ativo com timestamp velho
significa que ele não reiniciou — o código novo não está rodando.

**4. Processo na porta certa**

```bash
ss -ltnp | grep :<porta>
```

**5. Traefik roteando**

```bash
curl -sI http://172.18.0.1:<porta> | head -1
```

Se o backend responde direto mas o domínio não, o problema é o file provider do
Traefik, não a aplicação.

**6. Domínio público**

```bash
curl -sI https://<domínio> | head -3
```

`200` e certificado válido. Este é o único teste que prova o caminho inteiro.

## Prova de versão

O gate original exige ler de volta a superfície pública e confirmar que ela
declara a versão publicada. Vale adotar: exponha o SHA curto do build em algum
lugar acessível (rota `/health`, meta tag, header) e feche o ciclo:

```bash
curl -s https://<domínio>/health
```

O valor retornado tem que bater com o `git rev-parse --short HEAD` do passo 1.
Sem isso, você não tem como distinguir "deployei" de "achei que deployei" — que é
exatamente o buraco que o gate existe para tapar.

## Rollback

Do original, três regras que se aplicam igual:

- Tag/deploy errado: desfaça antes de republicar, não mute o publicado.
- Drift depois de publicar: corte um patch novo, não reescreva o anterior.
- Publicação falhou no meio: corrija, incremente a versão, publique de novo.
  Nunca reutilize o mesmo número de versão.

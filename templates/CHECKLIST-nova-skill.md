# Checklist — skill nova

Rode antes de commitar. Adaptado do `quality-bar.md` do AAS, cortando o que era
específico de PR comunitário.

## Automático

```bash
python3 /opt/workdev/gerar-indice.py --skills-dir /opt/workdev/skills --check
```

Isso cobre: `SKILL.md` existe, frontmatter parseia, `name` bate com a pasta,
`description` e `risk` presentes, id não duplicado.

**Passar aqui não é suficiente.** O validador confere estrutura, não sentido.

## Manual — o que o validador não vê

**Metadados**
- [ ] `description` com menos de 200 caracteres
- [ ] `description` lista gatilhos distintos, sem sinônimo repetindo o mesmo ramo
- [ ] `risk` corresponde ao comportamento real, não ao tema
- [ ] `date_added` no formato `AAAA-MM-DD`

**Gatilhos**
- [ ] Tem seção "Quando NÃO usar" com pelo menos um vizinho próximo
- [ ] Você consegue imaginar a frase exata do usuário que dispara isto
- [ ] Não colide com skill existente — `grep -i "<tema>" /opt/workdev/skills/_index.md`

**Conteúdo**
- [ ] Cada passo termina em critério de conclusão verificável
- [ ] Critérios são exaustivos onde importa ("toda linha", não "as linhas")
- [ ] Exemplos são reais e copiáveis, não inventados
- [ ] Seção de limitações existe e é honesta
- [ ] Menos de ~500 linhas; se passar, mova referência para arquivo irmão

**Segurança**
- [ ] Sem `curl | bash` ou equivalente
- [ ] Sem token, chave ou senha, nem de exemplo
- [ ] Comando destrutivo vem com pré-condição explícita
- [ ] Se `risk: critical`, o texto diz que a autorização vem do humano

```bash
grep -rniE 'sk-[a-zA-Z0-9]{16,}|eyJ[A-Za-z0-9_-]{20,}|ghp_|AKIA[0-9A-Z]{12}|curl.*\|.*sh' /opt/workdev/skills/<nome>/
```

Saída vazia é o esperado.

**Teste funcional — o que realmente prova**
- [ ] Você abriu um agente e pediu algo que deveria disparar a skill
- [ ] Ela disparou sem você citar o nome dela
- [ ] O resultado ficou melhor do que sem a skill

O terceiro item é o único que importa. Skill que dispara e não melhora nada é
custo de contexto puro — apague.

## Depois de passar

```bash
python3 /opt/workdev/gerar-indice.py --skills-dir /opt/workdev/skills
```

Reinjete o `_index.md` no Codex, Kimi e Qwen, e commite.

---
name: identidade-metadados-word
description: As quatro grafias com que o nome do Defensor aparece nos metadados dos arquivos Word, e por que o campo "criador" engana.
metadata:
  type: reference
---

Nos metadados dos .docx do acervo dele (`OneDrive - dpudef\DPU`), a autoria dele
aparece em quatro grafias distintas: `Lucas`, `Lucas Galdino`,
`Lucas Rafael Galdino de Araujo Lucena` e `lucas.lucena`. Qualquer varredura de
autoria precisa casar as quatro.

**Por que:** ele trocou de perfil do Word ao longo dos anos e entre máquinas
(Manaus, Rio Branco, Campina Grande).

**Como aplicar:** o campo `dc:creator` do `docProps/core.xml` **não** indica quem
escreveu o conteúdo — ele se propaga no "Salvar como". A biblioteca inteira em
`DPU\Modelos\` registra `viviane.moura`/`thiago.rocha` como criador, mas são
modelos dele, salvos-como a partir de um arquivo-base alheio. O sinal confiável
de que ele trabalhou no arquivo é `cp:lastModifiedBy`; o sinal de que o modelo é
dele é `lastModifiedBy` + texto assinado por ele + ausência de nome de assistido
no arquivo. Ver [[inventario-modelos-word-dpu]].

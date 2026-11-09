# Monitor de imóveis em Santos

Scripts para coleta e monitoramento de anúncios de apartamentos à venda em Santos, com filtros por perfil e geração de relatório HTML.

## Relatório

Abra `apartamentos_santos.html` no navegador. Para que os botões **Considerar** e **Excluir** persistam localmente, execute `abrir_relatorio.bat`; as decisões ficam em `decisoes_imoveis.sqlite3`, arquivo local que não deve ser publicado.

## Filtros do perfil principal

- Santos: Aparecida, Boqueirão, Embaré, Gonzaga e Pompéia.
- Até R$ 530.000, 2 quartos, área mínima de 70 m² e pelo menos uma vaga (vaga coletiva aceita).
- Não térreo; elevador confirmado; condomínio informado de até R$ 1.100.
- Condomínio e andar não informados são aceitos; avenidas são excluídas.

Os dados dos portais podem mudar ou estar incompletos. Confirme preço, disponibilidade e características na página original do anúncio.

## Segurança

Chaves SSH, arquivos `.env`, bancos de decisões, estados de execução e logs são locais e estão excluídos do Git.

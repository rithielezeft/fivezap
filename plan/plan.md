# WhatsFlow (fivezap): importar e rodar no preview

Trazer o repositório `rithielezeft/fivezap` para este ambiente e deixar o WhatsFlow funcionando no preview, do jeito que está, sem mudar recursos.
É um sistema de atendimento automático no WhatsApp para revenda de IPTV / P2P / Hybrid, ligado ao painel.fun e ao InfinitePay.

## Para quem é
- O dono da revenda (admin), que gerencia clientes, testes, renovações e mensagens automáticas.
- Os clientes finais, que pedem testes, recebem avisos e pagam renovações por link.

## Recursos principais (já existem no projeto e serão mantidos)
- Login admin com senha.
- Conexão do WhatsApp por QR code, com envio e recebimento de mensagens e imagens.
- Bot de comandos (ex.: `/teste iptv MAC`) que cria testes automaticamente no painel.fun.
- Modelos de mensagem editáveis, com prévia no estilo WhatsApp e envio de imagem.
- Avisos automáticos de vencimento (7/3/1/0 dias antes e 1/3/7 dias depois).
- Lembretes 1h e 3h depois que um teste é criado.
- Renovação por link de pagamento InfinitePay (`/pay/{cliente}`).
- Página pública `/teste`, onde o cliente pede o próprio teste.
- Painel com números gerais, lista de clientes e sincronização com o painel.fun.

## Fluxo do usuário
1. O admin abre o link do preview e entra com a senha.
2. Vai em **WhatsApp** e escaneia o QR code com o celular.
3. Em **Configurações**, preenche a InfiniteTag e os preços dos planos.
4. Ajusta as mensagens em **Notificações** e os comandos em **Comandos**.
5. Em **Clientes**, clica em "Atualizar do painel" para puxar os usuários do painel.fun.
6. A partir daí o bot responde, cria testes e envia avisos sozinho.

## Visual
Fica como está no repositório. Nenhuma mudança de design.

## Fases
- **Fase 1 (agora): importar e rodar.** Copiar o código, instalar o necessário e subir as três partes (painel web, servidor e serviço do WhatsApp). Corrigir só o que impedir de abrir ou de funcionar no preview. Confirmar que o login, as telas e o QR code do WhatsApp funcionam.
- **Fase 2: ligar as contas reais.** Conferir a ligação com o painel.fun e o InfinitePay usando as credenciais do admin, e testar a criação de teste e o link de pagamento de ponta a ponta.
- **Fase 3: mudanças pedidas.** Ajustes ou recursos novos que o dono pedir depois de ver tudo funcionando.

## Premissas
- O projeto é trazido do jeito que está; o código feito para Raspberry (instaladores, Nginx, systemd) fica no repositório, mas não é usado aqui.
- O banco atual (arquivo local SQLite) é mantido, como foi escolhido. No preview funciona normalmente, mas o arquivo pode ser apagado quando o ambiente reinicia ou se o app for publicado aqui. Para uso definitivo, o certo é continuar rodando na Raspberry ou trocar o banco depois.
- O WhatsApp é conectado de verdade: depois de escanear o QR code, mensagens reais vão para clientes reais. Se o ambiente reiniciar, pode ser preciso escanear de novo.
- A senha admin padrão do projeto continua valendo; dá para trocar em Configurações.
- As credenciais do painel.fun e do InfinitePay vêm da configuração já existente no projeto. Se faltar alguma, o sistema pede pela tela segura de chaves; nada é digitado no chat.
- Nenhum recurso é criado, removido ou redesenhado nesta fase.

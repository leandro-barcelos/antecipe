 # Antecipe — Plataforma de Análise de Recebíveis

## 1. Sobre o projeto

O Antecipe é uma plataforma de simulação de antecipação de recebíveis. A aplicação permite importar arquivos CSV com títulos, aplicar regras de elegibilidade configuráveis, calcular o valor líquido estimado dos recebíveis aprovados e apresentar justificativas para os títulos recusados.

O objetivo é tornar o processo de  análise mais transparente, fléxivel, interpretável,  automatizado e fácil de auditar.

## 2. Funcionalidades

- Importação de recebíveis por arquivo CSV.
- Validação dos dados dos títulos.
- Motor de regras configurável por JSON.
- Validação de CNPJ do sacado.
- Verificação da situação cadastral informada.
- Validação do tipo de recebível.
- Valor nominal mínimo.
- Verificação de vencimento e prazo máximo.
- Análise de concentração por sacado.
- Cálculo estimado do valor líquido de antecipação.
- Exibição dos motivos de recusa.
- Exportação dos resultados da análise.

## 3. Tecnologias utilizadas

### Frontend
- VueJS 3
- Vite
- Tailwind Css
- Axios

### Backend
- Python
- FastAPI
- Pytest
- Uvircon

### Configuração e dados
- biblioteca CSV do Python, processamento em blocos e ProcessPoolExecutor
- JSON para configuração das regras.
- CSV para importação e exportação de dados.

## 4. Estrutura do projeto

antecipe-hackathon/
├── backend/
│   ├── app/
│   │   ├── __pycache__/
│   │   ├── config.py
│   │   ├── csv-parser.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── portfolio.py
│   │   ├── pricing.py
│   │   ├── situacao_cadastral.py
│   │   ├── validation.py
│   │   └── validator.py
│   ├── config/
│   ├── requirements.txt
│   └── ...
├── frontend/
├── .vscode/
├── public/
├── src/
├── .gitignore
├── index.html
├── package-lock.json
├── package.json
└── README.md
├── PROMPTS_IA.md
└── README.md

## 5. Regras de elegibilidade

As regras foram definidas em um arquivo JSON, permitindo configurar quais validadores estão ativos e seus respectivos parâmetros.

Regras previstas:

| Regra | Descrição |
|---|---|
| CNPJ_SACADO_VALIDO | Valida os dígitos verificadores do CNPJ |
| SITUACAO_CADASTRAL_SACADO | Verifica a situação cadastral aceita |
| TIPO_RECEBIVEL | Aceita os tipos configurados |
| VALOR_MINIMO | Verifica o valor nominal mínimo |
| NAO_VENCIDA | Rejeita títulos vencidos |
| PRAZO_MAXIMO | Limita o prazo até o vencimento |
| CONCENTRACAO_MAXIMA_SACADO | Controla a concentração por raiz do CNPJ |
| PRAZO_MINIMO | Controla a concentração por raiz do CNPJ |
| CONCENTRACAO_MAXIMA_CEDENTE | Controla a concentração por raiz do CNPJ |

As regras de concentração dependem da exposição considerada e da carteira existente. 

## 6. Precificação

A simulação utiliza desconto simples, com taxa mensal de 2% e base de 30 dias, conforme a configuração inicial.

Fórmula:

Desconto = Valor Nominal * (Taxa Mensal * Taxa mensal percentual/100) * (prazo_dias/base_diasrazo em Dias / Base de Dias)

Valor Líquido = Valor Nominal − Desconto

A precificação é uma estimativa para demonstração e deve respeitar as regras de negócio definitivas do desafio.

## 7. Como executar localmente

### Pré-requisitos

docker Instalado.

## 8. Como utilizar

1. docker compose up --build -d

## 10. Principais decisões tomadas:

# Arquitetura modular: 
separação entre leitura de arquivos, validação de elegibilidade, análise de carteira e precificação, facilitando a manutenção e a evolução do sistema.

# Processamento eficiente:
leitura de arquivos CSV em blocos, com suporte a processamento paralelo para operações independentes.

# Motor de regras configurável:
Utilização do arquivo validadores_antecipe.json para definir validadores ativos e seus parâmetros, evitando valores fixos na lógica de negócio.

# Análise de carteira:
Utilização do estoque histórico para verificar possíveis duplicidades e calcular a concentração de recebíveis por sacado.

# Precisão financeira:
Utilização de aritmética decimal para calcular descontos e valores líquidos.

# Arquitetura com banco de dados:
Utilização de arquivos CSV, JSON e  SQLit, reduzindo a complexidade da infraestrutura e facilitando a execução do projeto.

## 11 Limitações e funcionalidades não contempladas

- Integração definitiva com serviços externos para consulta da situação cadastral dos CNPJs.
- Autenticação e gerenciamento de usuários.
- Infraestrutura distribuída e escalabilidade horizontal.

## 12. Licença

Projeto desenvolvido para fins de participação no hackathon Antecipe. 

## 13. Considerações Finais

A solução prioriza a simplicidade arquitetural, a eficiência do processamento e a transparência das decisões de elegibilidade. Sua estrutura modular permite futuras evoluções, incluindo persistência de dados, integração com serviços externos e mecanismos adicionais de segurança e escalabilidade


 ## 12 Integrantes do Grupo:
 1. Eneia Gazite
 2. Abdelkader Tagmoni
 3. Leandro Barcelos

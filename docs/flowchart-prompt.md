# Prompt para Geração de Fluxograma — D2T Pipeline

## Prompt (copie e cole no gerador de imagem)

```
Create a clean, minimal horizontal flowchart diagram on a white background showing a data-to-text pipeline with exactly 4 stages flowing left to right, connected by arrows.

Stage 1 — "Data Sources" (on the left): Show a small group of 3 stacked icons representing data inputs: a cylinder icon labeled "SQL Query" on top, another cylinder labeled "SQL Query" in the middle, and a document/file icon labeled "Static CSV" at the bottom. These 3 icons are grouped together inside a light gray dashed rounded rectangle.

Stage 2 — "Analysis Strategy" (center-left): A single blue rounded rectangle box labeled "Analysis Strategy (Python)". Multiple arrows come from the data sources group into this single box, converging into it.

Stage 3 — "Templates" (center-right): Two orange rounded rectangle boxes stacked vertically, labeled "Template A (Jinja2)" and "Template B (Jinja2)". Arrows fan out from the single Analysis Strategy box to both template boxes.

Stage 4 — "Output" (on the right): Two green rounded rectangle boxes stacked vertically, labeled "Callout" and "Detailed Report", each connected by an arrow from its corresponding template box.

Style: flat design, no shadows, no gradients, soft pastel colors (light blue, light orange, light green), thin dark gray arrows with arrowheads, clean sans-serif font (like Inter or Helvetica), generous whitespace, professional and minimalist look suitable for technical documentation. No extra decorations or background patterns. The diagram should be wide (landscape orientation, roughly 16:9 aspect ratio).
```

## Prompt alternativo (versão mais curta / simplificada)

```
Minimal flat-design horizontal flowchart on white background, 16:9 landscape ratio. Left to right: (1) a dashed gray box containing 3 small icons — two database cylinders labeled "SQL" and one file icon labeled "CSV"; (2) a single light-blue rounded box labeled "Analysis Strategy"; (3) two light-orange rounded boxes stacked vertically labeled "Template A" and "Template B"; (4) two light-green rounded boxes labeled "Callout" and "Detailed Report". Thin gray arrows connect the stages: multiple arrows converge from the data sources into the single analysis box, then fan out to both templates, then each template connects to its output. Clean sans-serif font, pastel colors, no shadows, no gradients, professional technical documentation style.
```

## Explicação do Fluxograma

O fluxograma acima ilustra como os callouts são gerados automaticamente. O processo começa com a **extração de dados**, que podem vir de múltiplas fontes — diferentes queries SQL ou arquivos CSV estáticos (como tabelas de lookup). Esses dados são então enviados para o módulo de **Analysis Strategy**, que executa toda a lógica de análise: agregações, comparações YoY/WoW, identificação de top drivers e detractors, entre outros. O resultado dessa análise é um conjunto estruturado de insights que alimenta um ou mais **templates Jinja2** — cada template formata os mesmos dados de uma maneira diferente, permitindo gerar tanto um callout executivo resumido quanto um relatório detalhado a partir de uma única análise. O **output** final é o texto pronto para uso em apresentações, emails ou dashboards.

## Próximos Passos desta Iniciativa

Esta iniciativa será desenvolvida em três etapas progressivas:

1. **Callouts semanais com feedback contínuo:** Inicialmente, irei enviar os callouts em um template pré-determinado para cada uma das categorias semanalmente. Os HOSSes e CMMs irão compartilhar feedbacks e ideias adicionais para aprimorar este template para as próximas semanas, garantindo que o conteúdo evolua de forma colaborativa e alinhada às necessidades de cada equipe.

2. **Análises e insights avançados com apoio de AI:** Na segunda etapa, passaremos a evoluir para análises e insights mais avançados, utilizando inclusive o apoio da AI para encontrar findings adicionais e priorizar temas para darmos destaque no WBR — indo além das métricas básicas para identificar padrões, anomalias e oportunidades de forma proativa.

3. **Democratização da ferramenta:** Por fim, compartilharei a codebase deste projeto para que cada ROS e CMM possa utilizar ferramentas de codificação com AI, como o Cline, para criar análises e templates adicionais específicos para suas necessidades — permitindo que cada equipe personalize seus próprios callouts sem depender de suporte centralizado.

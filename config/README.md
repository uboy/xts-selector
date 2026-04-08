# Config Rule Files

В каталоге `config/` лежат настраиваемые правила selector. Их нужно менять здесь, а не в `src/arkui_xts_selector/cli.py`, если задача сводится к настройке признаков, группировок и весов.

## Какие файлы за что отвечают

- `path_rules.json`
  - алиасы компонент и модификаторов;
  - специальные path-token правила;
  - используется при построении сигналов для changed file и query.
  - сюда же нужно добавлять альтернативные spellings и casing, если XTS использует другой стиль имени, например `CheckBoxGroup` vs `CheckboxGroup`.

- `composite_mappings.json`
  - правила для файлов, которые затрагивают сразу несколько компонент или общий bridge/helper слой;
  - добавляет family, symbols, hints и required-method сигналы.

- `ranking_rules.json`
  - признаки и веса ранжирования;
  - family-группы для coverage planner;
  - capability-группы для более точного planner внутри одной family;
  - generic/umbrella токены;
  - коэффициенты `scope`, `bucket`, quality и planner.

- `changed_file_exclusions.json`
  - префиксы путей, которые не должны участвовать в XTS-анализе;
  - по умолчанию сюда входят `test/unittest` и `test/mock`.

## Как добавлять или удалять правила в `ranking_rules.json`

### `generic_tokens.path`

Используйте для низкосигнальных токенов пути, которые не должны считаться признаком отдельной функциональности.

- Добавляйте только общие инфраструктурные слова.
- Удаляйте токен, если он начал скрывать реальную component family.

### `generic_tokens.scope`

Используйте для широких XTS-доменов вроде `commonattrs`, `dialog`, `interactiveattributes`.

- Добавляйте сюда umbrella-термины, если suite из-за них поднимается слишком высоко.
- Удаляйте токен, если он, наоборот, нужен как самостоятельная functional family.

### `generic_tokens.low_signal_specificity`

Это слабые слова из инфраструктурных файлов и explain-reasons.

- Добавляйте слова вроде `helper`, `accessor`, `implementation`, если они шумят в ранжировании.
- Не добавляйте сюда реальные component names.

### `generic_tokens.coverage_extra`

Это служебные токены coverage planner, которые нужно игнорировать при нормализации family.

- Добавляйте сюда только технические слова верхнего уровня.
- Не кладите сюда names компонентов, иначе planner перестанет строить family coverage.

### `coverage_family_groups`

Здесь один token приводится к общей functional family.

Примеры:
- `navdestination -> navigation_stack`
- `textinput -> text_input`
- `webviewcontroller -> web`

Как менять:
- добавляйте новое правило, если несколько близких API должны считаться одной functional family;
- удаляйте правило, если family стала слишком широкой и мешает отличать разные тесты.

### `coverage_capability_groups`

Здесь token приводится к более узкой capability внутри уже существующей family.

Примеры:
- `tabcontent -> navigation_stack.tabs`
- `navdestination -> navigation_stack.destination`
- `navigation -> navigation_stack.navigation`
- `checkboxgroupcontentmodifier -> checkboxgroup.modifier`

Назначение:
- family по-прежнему отвечает за общий coverage area;
- capability нужна, чтобы planner различал несколько разных подзон внутри одной family и не выбирал один broad suite на всё подряд.

Как менять:
- добавляйте правило, если внутри одной family нужно различать независимые functional sub-areas;
- используйте формат `<family>.<subarea>`, чтобы planner мог сохранить связь с родительской family;
- не привязывайтесь к именам suite, описывайте только архитектурные токены API/компонента;
- удаляйте правило, если sub-area получилась слишком узкой и даёт ложные дубли вместо полезного разбиения.

### `scope_gain_multiplier`

Вес `scope_tier`:
- `direct` - самый узкий и предпочтительный тест;
- `focused` - хороший, но не полностью прямой;
- `broad` - широкий umbrella suite.

Если broad-suite слишком часто выигрывают, снижайте `broad`.

### `bucket_gain_multiplier`

Вес confidence bucket:
- `must-run`
- `high-confidence related`
- `possible related`

Если selector слишком агрессивно рекомендует слабые совпадения, снижайте нижние bucket-ы.

### `umbrella_penalties`

Штрафы за широкие suite-ы.

- `markers` - penalty по generic marker token, например `apilack`;
- `family_count_threshold` - с какого числа families начинается дополнительный штраф;
- `family_count_penalty` - penalty за каждую extra family;
- `family_count_penalty_cap` - максимум этого дополнительного штрафа;
- `penalty_cap` - общий потолок umbrella penalty;
- `minimum_factor` - как низко umbrella factor может опускать suite.

### `family_quality`

Коэффициенты для выбора лучшего представителя внутри одной family.

- `project_tokens` - бонус за прямое совпадение на уровне project path;
- `related_file_path` - бонус за path hit в top file;
- `direct_file_path` - дополнительный бонус, если top file имеет прямое evidence;
- `direct_reason_tokens` - бонус за reason tokens из direct evidence;
- `direct_single_family_bonus` - бонус для suite с единственной прямой family;
- `direct_small_family_bonus` - бонус для suite с маленьким набором families;
- `maximum_quality` - верхний предел качества;
- `direct_gain_base` / `related_gain_base` - базовый gain direct/related overlap;
- `minimum_direct_quality` / `minimum_related_quality` - нижняя граница quality factor.

### `representative_quality`

Это отдельный слой выбора лучшего representative suite внутри уже выбранной functional family.

- `project_family_hit` - бонус, если family видна прямо в project path;
- `file_family_hit` - бонус за совпадение family в path top matching files;
- `reason_family_hit` - бонус за family в reason tokens;
- `direct_file_hit` - дополнительный бонус, если direct evidence пришёл из matching file этой family;
- `direct_family_bonus` - бонус suite, который прямо владеет этой family;
- `single_family_bonus` - бонус для узкого suite с одной family;
- `small_family_bonus` - бонус для маленького direct suite;
- `source_token_overlap_weight` / `source_token_overlap_cap` - вес и предел за overlap source-specific tokens вроде `tabcontent`, `styledstring`, `checkboxgroup`;
- `extra_family_penalty` / `extra_family_penalty_cap` - штраф за лишние families внутри suite;
- `umbrella_penalty_weight` - как сильно umbrella penalty давит на representative quality;
- `direct_overlap_multiplier` / `related_overlap_multiplier` - финальный multiplier для direct/related source-family overlap;
- `minimum_quality` / `maximum_quality` - нижняя и верхняя граница representative score.

### `planner`

Глобальные коэффициенты coverage planner.

- `fallback_no_family_gain` - gain для changed source, у которого не удалось нормализовать family;
- `rank_weight_power` - насколько сильно penalize поздние file hits;
- `rank_weight_floor` - минимальный rank для формулы.

## Практика изменения правил

1. Меняйте только одну группу правил за раз.
2. После каждого изменения проверяйте selector на 1-2 реальных PR.
3. Если меняете `coverage_family_groups`, `coverage_capability_groups` или `generic_tokens`, пересматривайте top recommended и optional duplicate coverage вместе.
4. Если меняете коэффициенты, обязательно прогоняйте unit tests selector.

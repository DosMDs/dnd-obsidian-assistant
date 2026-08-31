---
apply: ALWAYS
mode: AGENT
---

# Tool usage policy

Для чтения и изменения файлов проекта используй встроенные файловые
инструменты GigaCode/IDE.

Для изменения файлов НЕ используй shell/PowerShell, если доступен
встроенный файловый инструмент.

Запрещено использовать для редактирования исходников, тестов и других
repository text files:

- Set-Content
- Add-Content
- Out-File
- [System.IO.File]::WriteAllText
- [System.IO.File]::WriteAllLines
- shell redirect `>` / `>>`
- PowerShell StringBuilder + последующую перезапись файла
- Python/PowerShell one-liner как замену встроенному edit/write tool
- bash/PowerShell/Python scripts как обход ошибки edit/write tool
- base64/temporary-script generation как обход встроенного file tool

## Absolute prohibition on indirect shell file writes

Запрет shell-based editing распространяется не только на shell redirection.

Любая команда, запущенная через shell, которая вызывает другой интерпретатор
или runtime для изменения repository file, считается shell-based file
mutation.

В частности, без явного предварительного разрешения пользователя запрещены:

```text
python -c "open(..., 'w').write(...)"
python -c "open(..., 'a').write(...)"
python -c "Path(...).write_text(...)"
python -c "Path(...).open(...).write(...)"
python <temporary-generator-script>.py

powershell -Command "...file write..."
cmd /c "... > file"
```

Запрет одинаково распространяется на:

```text
create
overwrite
append
insert
patch
```

repository text files.

Фраза «мне нужно только дописать несколько строк» не является исключением.

Большой размер изменения также не является исключением.

Если встроенный edit/write не принимает большой payload, обязательный
следующий шаг:

```text
smaller IDE edit
```

а не:

```text
Python/PowerShell/Bash file mutation
```

Конкретный алгоритм incremental editing определён в:

```text
.gigacode/rules/07-incremental-file-editing.md
```

## Recovery after edit/write tool failures

Ошибка JSON parsing, oversized/large payload, timeout, transport failure или
другой технический сбой встроенного edit/write tool НЕ означает, что файловый
инструмент «неспособен» выполнить задачу, и НЕ разрешает автоматически
переходить на shell/PowerShell/Python для записи файла.

В таком случае агент обязан:

1. Сначала проверить текущее состояние working tree и уже успешно внесённые
   изменения (`git status`, `git diff`, чтение затронутого файла).
2. Не перезаписывать корректную частичную работу без необходимости.
3. Повторить изменение через встроенные файловые инструменты более мелкими
   атомарными операциями:
   - создать небольшой начальный файл;
   - затем дополнять или patch/edit логическими секциями;
   - избегать одного чрезмерно большого write payload.
4. Если причиной стал большой тестовый файл, сначала уменьшить ненужное
   дублирование через pytest parametrization/helpers, сохранив acceptance
   criteria, regression coverage и читаемость.
5. После восстановления проверить final diff и убедиться, что не осталось:
   - обрезанного файла;
   - частичной неудачной записи;
   - дублированных секций;
   - случайных изменений вне задачи.

Shell fallback допустим только когда встроенные файловые инструменты реально
недоступны или объективно не поддерживают требуемую операцию независимо от
размера payload/JSON transport.

Перед таким fallback агент обязан:

1. сообщить пользователю конкретную причину;
2. получить явное согласование;
3. ограничить изменение минимально необходимым файлом/операцией;
4. после операции проверить diff.

`run_shell_command` используй только для выполнения команд разработки:

- uv
- pytest
- ruff
- git
- запуск CLI
- диагностические команды, не изменяющие исходные файлы

После любых изменений проверяй git diff.

Все текстовые файлы проекта сохраняй в UTF-8.

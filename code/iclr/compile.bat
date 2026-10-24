@echo off
REM 编译 ICLR 论文。TeX 发行版路径可用 PAPER_TEXBIN 覆盖，
REM 未设置时按 TinyTeX / MiKTeX 的常见安装位置依次探测。
setlocal

if defined PAPER_TEXBIN (
  set "TEXBIN=%PAPER_TEXBIN%"
) else if exist "%LOCALAPPDATA%\TinyTeX\TinyTeX\bin\windows\pdflatex.exe" (
  set "TEXBIN=%LOCALAPPDATA%\TinyTeX\TinyTeX\bin\windows"
) else if exist "%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64\pdflatex.exe" (
  set "TEXBIN=%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64"
) else if exist "C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe" (
  set "TEXBIN=C:\Program Files\MiKTeX\miktex\bin\x64"
) else if exist "D:\MikTex\miktex\bin\x64\pdflatex.exe" (
  set "TEXBIN=D:\MikTex\miktex\bin\x64"
) else (
  echo 未找到 pdflatex。请安装 TinyTeX 或 MiKTeX，或设置 PAPER_TEXBIN 指向其 bin 目录。
  exit /b 1
)
set "PATH=%TEXBIN%;%PATH%"

cd /d "%~dp0"
echo TEXBIN=%TEXBIN%

pdflatex -interaction=nonstopmode iclr_paper.tex
bibtex iclr_paper
pdflatex -interaction=nonstopmode iclr_paper.tex
pdflatex -interaction=nonstopmode iclr_paper.tex

if exist iclr_paper.pdf (
  echo PDF OK: iclr_paper.pdf
  exit /b 0
)
echo PDF FAILED - see iclr_paper.log
exit /b 1
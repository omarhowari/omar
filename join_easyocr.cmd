@echo off
cd /d "%~dp0"
echo Joining EasyOCR add-on files...
copy /b InvoiceLite_EasyOCR_Libs_1.8.0.exe.part0+InvoiceLite_EasyOCR_Libs_1.8.0.exe.part1 InvoiceLite_EasyOCR_Libs_1.8.0.exe
copy /b InvoiceLite_EasyOCR_Models_1.8.0.exe.part0+InvoiceLite_EasyOCR_Models_1.8.0.exe.part1+InvoiceLite_EasyOCR_Models_1.8.0.exe.part2 InvoiceLite_EasyOCR_Models_1.8.0.exe
echo Done.
pause

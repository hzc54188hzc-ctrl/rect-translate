# 划词翻译的验收靶子：一个带可选文本框的窗口，打开即聚焦并全选。
# 用法：powershell -NoProfile -File tests\15-text-selection.ps1

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Selection Target'
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point 200, 200
$form.Size = New-Object System.Drawing.Size 720, 200
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::White

$box = New-Object System.Windows.Forms.TextBox
$box.Multiline = $true
$box.Dock = 'Fill'
$box.Font = New-Object System.Drawing.Font 'Segoe UI', 14
$box.Text = 'Please translate this selected sentence into Chinese.'
$form.Controls.Add($box)

$form.Add_Shown({
    $form.Activate()
    $box.Focus()
    $box.SelectAll()
})

[System.Windows.Forms.Application]::Run($form)

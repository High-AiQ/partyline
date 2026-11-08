param([ValidateSet('fixture','open','save')][string]$Mode = 'fixture')
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
if ($Mode -ne 'fixture') {
    $dialog = if ($Mode -eq 'open') { New-Object System.Windows.Forms.OpenFileDialog } else {
        New-Object System.Windows.Forms.SaveFileDialog
    }
    $dialog.Title = "Partyline $Mode dialog"
    $dialog.InitialDirectory = $env:PARTYLINE_CORPUS_DIR
    $dialog.FileName = 'example.txt'
    $dialog.AddExtension = $false
    [void]$dialog.ShowDialog()
    exit
}
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Partyline WinForms corpus'
$form.Size = New-Object System.Drawing.Size(600,450)
$entry = New-Object System.Windows.Forms.TextBox
$entry.AccessibleName = 'Corpus value'
$entry.Text = 'before'
$entry.Location = New-Object System.Drawing.Point(20,20)
$form.Controls.Add($entry)
$check = New-Object System.Windows.Forms.CheckBox
$check.Text = 'Enable preview'
$check.Location = New-Object System.Drawing.Point(20,60)
$form.Controls.Add($check)
$i = 0
foreach ($name in @('Apply','Apply','Unavailable','Outside view')) {
    $button = New-Object System.Windows.Forms.Button
    $button.Text = $name
    $button.Location = New-Object System.Drawing.Point(20,(100 + $i * 50))
    if ($name -eq 'Unavailable') { $button.Enabled = $false }
    if ($name -eq 'Outside view') { $button.Location = New-Object System.Drawing.Point(900,900) }
    $form.Controls.Add($button)
    $i++
}
[void]$form.ShowDialog()

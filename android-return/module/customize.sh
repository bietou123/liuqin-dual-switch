SKIPMOUNT=true
ui_print 'Installs a safety template only: no flash, no reboot, no automatic Root setup.'
ui_print 'Fill the root-only config.txt with independently reviewed per-device values.'
cp "$MODPATH/config.txt.example" "$MODPATH/config.txt"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm "$MODPATH/config.txt" 0 0 0600
set_perm "$MODPATH/action.sh" 0 0 0755
set_perm "$MODPATH/service.sh" 0 0 0755

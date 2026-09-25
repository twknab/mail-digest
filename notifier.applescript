-- Compiled by install.sh into MailDigest.app.
--
-- This exists for one reason: `osascript -e 'display notification ...'` is
-- attributed to osascript, which has no bundle identity, so macOS silently
-- drops it and there is nothing in System Settings to allow. A compiled applet
-- is a real app bundle, so it gets its own Notification Center entry and the
-- notification actually arrives.
--
--   open -a MailDigest.app --args "Title" "Message" "Subtitle"

on run argv
	set theTitle to "Mail digest"
	set theMessage to "A digest is ready."
	set theSubtitle to ""

	if (count of argv) > 0 then set theTitle to item 1 of argv
	if (count of argv) > 1 then set theMessage to item 2 of argv
	if (count of argv) > 2 then set theSubtitle to item 3 of argv

	if theSubtitle is "" then
		display notification theMessage with title theTitle sound name "Ping"
	else
		display notification theMessage with title theTitle subtitle theSubtitle sound name "Ping"
	end if
end run

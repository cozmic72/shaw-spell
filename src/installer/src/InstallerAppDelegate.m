//
//  InstallerAppDelegate.m
//  Shaw Spell Installer
//
//  Implements the installer UI and installation logic.
//

#import "InstallerAppDelegate.h"
#import <sys/stat.h>

@implementation InstallerAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    // Create the main window
    NSRect windowRect = NSMakeRect(0, 0, 600, 500);
    NSUInteger windowStyle = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable;

    self.window = [[NSWindow alloc] initWithContentRect:windowRect
                                              styleMask:windowStyle
                                                backing:NSBackingStoreBuffered
                                                  defer:NO];
    [self.window setTitle:@"Install Shaw Spell"];
    [self.window center];

    // Create content view
    NSView *contentView = [self.window contentView];

    // Title label
    NSTextField *titleLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 440, 560, 40)];
    [titleLabel setStringValue:@"Shaw Spell Installer"];
    [titleLabel setBezeled:NO];
    [titleLabel setDrawsBackground:NO];
    [titleLabel setEditable:NO];
    [titleLabel setSelectable:NO];
    [titleLabel setFont:[NSFont boldSystemFontOfSize:24]];
    [titleLabel setAlignment:NSTextAlignmentCenter];
    [contentView addSubview:titleLabel];

    // Subtitle
    NSTextField *subtitleLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 410, 560, 20)];
    [subtitleLabel setStringValue:@"Shavian Dictionaries & Spell Checker for macOS"];
    [subtitleLabel setBezeled:NO];
    [subtitleLabel setDrawsBackground:NO];
    [subtitleLabel setEditable:NO];
    [subtitleLabel setSelectable:NO];
    [subtitleLabel setFont:[NSFont systemFontOfSize:12]];
    [subtitleLabel setAlignment:NSTextAlignmentCenter];
    [subtitleLabel setTextColor:[NSColor secondaryLabelColor]];
    [contentView addSubview:subtitleLabel];

    // Options section
    NSTextField *optionsLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 370, 200, 20)];
    [optionsLabel setStringValue:@"Installation Options:"];
    [optionsLabel setBezeled:NO];
    [optionsLabel setDrawsBackground:NO];
    [optionsLabel setEditable:NO];
    [optionsLabel setSelectable:NO];
    [optionsLabel setFont:[NSFont boldSystemFontOfSize:14]];
    [contentView addSubview:optionsLabel];

    // Dialect checkboxes
    self.dialectGBCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(40, 340, 250, 20)];
    [self.dialectGBCheckbox setButtonType:NSButtonTypeSwitch];
    [self.dialectGBCheckbox setTitle:@"British English (GB)"];
    [self.dialectGBCheckbox setState:NSControlStateValueOn];
    [contentView addSubview:self.dialectGBCheckbox];

    self.dialectUSCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(40, 315, 250, 20)];
    [self.dialectUSCheckbox setButtonType:NSButtonTypeSwitch];
    [self.dialectUSCheckbox setTitle:@"American English (US)"];
    [self.dialectUSCheckbox setState:NSControlStateValueOff];
    [contentView addSubview:self.dialectUSCheckbox];

    // System-wide checkbox
    self.systemWideCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(40, 285, 300, 20)];
    [self.systemWideCheckbox setButtonType:NSButtonTypeSwitch];
    [self.systemWideCheckbox setTitle:@"Install system-wide (requires admin password)"];
    [self.systemWideCheckbox setState:NSControlStateValueOff];
    [contentView addSubview:self.systemWideCheckbox];

    // Instructions section
    NSTextField *instructionsLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 245, 200, 20)];
    [instructionsLabel setStringValue:@"What will be installed:"];
    [instructionsLabel setBezeled:NO];
    [instructionsLabel setDrawsBackground:NO];
    [instructionsLabel setEditable:NO];
    [instructionsLabel setSelectable:NO];
    [instructionsLabel setFont:[NSFont boldSystemFontOfSize:14]];
    [contentView addSubview:instructionsLabel];

    // Instructions text view
    NSScrollView *scrollView = [[NSScrollView alloc] initWithFrame:NSMakeRect(20, 100, 560, 135)];
    [scrollView setHasVerticalScroller:YES];
    [scrollView setHasHorizontalScroller:NO];
    [scrollView setAutohidesScrollers:YES];
    [scrollView setBorderType:NSBezelBorder];

    self.instructionsView = [[NSTextView alloc] initWithFrame:NSMakeRect(0, 0, 545, 135)];
    [self.instructionsView setEditable:NO];
    [self.instructionsView setSelectable:YES];
    [self.instructionsView setFont:[NSFont systemFontOfSize:11]];
    [self.instructionsView setTextContainerInset:NSMakeSize(5, 5)];

    NSString *instructions = @"Shaw Spell includes:\n\n"
        @"• Three complete dictionaries for Dictionary.app:\n"
        @"  - Shavian → English (look up Shavian words)\n"
        @"  - English → Shavian (look up English words)\n"
        @"  - Shavian → Shavian (pure Shavian dictionary)\n\n"
        @"• Hunspell spell-checking dictionaries\n"
        @"  Works with: LibreOffice, Firefox, Emacs, VSCode, etc.\n\n"
        @"• NSSpellServer service for native macOS apps\n"
        @"  Works with: TextEdit, Pages, Mail, Notes, etc.\n\n"
        @"After installation:\n"
        @"1. Restart Dictionary.app to use the dictionaries\n"
        @"2. The spell server will start automatically\n"
        @"3. Configure spell-checking in System Settings > Keyboard > Text Input";

    [self.instructionsView setString:instructions];
    [scrollView setDocumentView:self.instructionsView];
    [contentView addSubview:scrollView];

    // Status label
    self.statusLabel = [[NSTextField alloc] initWithFrame:NSMakeRect(20, 65, 560, 20)];
    [self.statusLabel setStringValue:@"Ready to install"];
    [self.statusLabel setBezeled:NO];
    [self.statusLabel setDrawsBackground:NO];
    [self.statusLabel setEditable:NO];
    [self.statusLabel setSelectable:NO];
    [self.statusLabel setAlignment:NSTextAlignmentCenter];
    [self.statusLabel setTextColor:[NSColor secondaryLabelColor]];
    [contentView addSubview:self.statusLabel];

    // Progress indicator
    self.progressIndicator = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(200, 40, 200, 20)];
    [self.progressIndicator setStyle:NSProgressIndicatorStyleBar];
    [self.progressIndicator setIndeterminate:YES];
    [self.progressIndicator setHidden:YES];
    [contentView addSubview:self.progressIndicator];

    // Install button
    self.installButton = [[NSButton alloc] initWithFrame:NSMakeRect(240, 10, 120, 30)];
    [self.installButton setTitle:@"Install"];
    [self.installButton setBezelStyle:NSBezelStyleRounded];
    [self.installButton setKeyEquivalent:@"\r"];
    [self.installButton setTarget:self];
    [self.installButton setAction:@selector(installButtonClicked:)];
    [contentView addSubview:self.installButton];

    [self.window makeKeyAndOrderFront:nil];
    [[NSApplication sharedApplication] activateIgnoringOtherApps:YES];
}

- (void)installButtonClicked:(id)sender {
    // Validate selection
    BOOL installGB = ([self.dialectGBCheckbox state] == NSControlStateValueOn);
    BOOL installUS = ([self.dialectUSCheckbox state] == NSControlStateValueOn);

    if (!installGB && !installUS) {
        NSAlert *alert = [[NSAlert alloc] init];
        [alert setMessageText:@"No dialect selected"];
        [alert setInformativeText:@"Please select at least one dialect to install (British or American English)."];
        [alert setAlertStyle:NSAlertStyleWarning];
        [alert addButtonWithTitle:@"OK"];
        [alert runModal];
        return;
    }

    // Disable button and show progress
    [self.installButton setEnabled:NO];
    [self.progressIndicator setHidden:NO];
    [self.progressIndicator startAnimation:nil];
    [self.statusLabel setStringValue:@"Installing..."];

    // Perform installation in background
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
        [self performInstallation];
    });
}

- (void)performInstallation {
    BOOL installGB = ([self.dialectGBCheckbox state] == NSControlStateValueOn);
    BOOL installUS = ([self.dialectUSCheckbox state] == NSControlStateValueOn);
    BOOL systemWide = ([self.systemWideCheckbox state] == NSControlStateValueOn);

    // Get the project root (assuming installer is in project/installer/)
    NSString *installerPath = [[NSBundle mainBundle] bundlePath];
    NSString *projectRoot = [installerPath stringByDeletingLastPathComponent];

    // Build installation script
    NSMutableString *script = [[NSMutableString alloc] init];
    [script appendString:@"#!/bin/bash\n"];
    [script appendString:@"set -e\n\n"];

    // Determine installation directories
    NSString *dictDir = systemWide ? @"/Library/Dictionaries" : @"$HOME/Library/Dictionaries";
    NSString *spellingDir = systemWide ? @"/Library/Spelling" : @"$HOME/Library/Spelling";
    NSString *servicesDir = systemWide ? @"/Library/Services" : @"$HOME/Library/Services";
    NSString *launchAgentDir = @"$HOME/Library/LaunchAgents";

    [script appendFormat:@"PROJECT_ROOT='%@'\n", projectRoot];
    [script appendFormat:@"DICT_DIR='%@'\n", dictDir];
    [script appendFormat:@"SPELLING_DIR='%@'\n", spellingDir];
    [script appendFormat:@"SERVICES_DIR='%@'\n", servicesDir];
    [script appendFormat:@"LAUNCH_AGENT_DIR='%@'\n\n", launchAgentDir];

    // Create directories
    [script appendString:@"echo 'Creating directories...'\n"];
    [script appendString:@"mkdir -p \"$DICT_DIR\"\n"];
    [script appendString:@"mkdir -p \"$SPELLING_DIR\"\n"];
    [script appendString:@"mkdir -p \"$SERVICES_DIR\"\n"];
    [script appendString:@"mkdir -p \"$LAUNCH_AGENT_DIR\"\n"];
    [script appendString:@"mkdir -p \"$HOME/Library/Logs\"\n\n"];

    // Install dictionaries
    if (installGB) {
        [script appendString:@"echo 'Installing British English dictionaries...'\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/Shavian-English-gb.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/English-Shavian-gb.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/Shavian-gb.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp \"$PROJECT_ROOT/build/shaw-gb.dic\" \"$SPELLING_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp \"$PROJECT_ROOT/build/shaw-gb.aff\" \"$SPELLING_DIR/\" 2>/dev/null || true\n\n"];
    }

    if (installUS) {
        [script appendString:@"echo 'Installing American English dictionaries...'\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/Shavian-English-us.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/English-Shavian-us.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp -R \"$PROJECT_ROOT/build/dictionaries/Shavian-us.dictionary\" \"$DICT_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp \"$PROJECT_ROOT/build/shaw-us.dic\" \"$SPELLING_DIR/\" 2>/dev/null || true\n"];
        [script appendString:@"cp \"$PROJECT_ROOT/build/shaw-us.aff\" \"$SPELLING_DIR/\" 2>/dev/null || true\n\n"];
    }

    // Install spell server
    [script appendString:@"echo 'Installing spell server...'\n"];
    [script appendString:@"cp -R \"$PROJECT_ROOT/build/ShavianSpellServer.service\" \"$SERVICES_DIR/\"\n\n"];

    // Install LaunchAgent
    [script appendString:@"echo 'Installing LaunchAgent...'\n"];
    [script appendString:@"sed \"s|__HOME__|$HOME|g\" \"$PROJECT_ROOT/src/spellserver/io.joro.shaw-spell.spellserver.plist\" > \"$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist\"\n\n"];

    // Load LaunchAgent
    [script appendString:@"echo 'Starting spell server...'\n"];
    [script appendString:@"launchctl unload \"$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist\" 2>/dev/null || true\n"];
    [script appendString:@"launchctl load \"$LAUNCH_AGENT_DIR/io.joro.shaw-spell.spellserver.plist\"\n\n"];

    // Update services
    [script appendString:@"echo 'Updating system services...'\n"];
    [script appendString:@"/System/Library/CoreServices/pbs -update 2>/dev/null || true\n\n"];

    [script appendString:@"echo 'Installation complete!'\n"];

    // Write script to temporary file
    NSString *scriptPath = @"/tmp/shaw-spell-install.sh";
    NSError *error = nil;
    [script writeToFile:scriptPath atomically:YES encoding:NSUTF8StringEncoding error:&error];

    if (error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [self showError:[NSString stringWithFormat:@"Failed to create installation script: %@", [error localizedDescription]]];
        });
        return;
    }

    // Make script executable
    chmod([scriptPath UTF8String], 0755);

    // Execute installation script
    NSTask *task = [[NSTask alloc] init];
    [task setLaunchPath:@"/bin/bash"];
    [task setArguments:@[scriptPath]];

    NSPipe *outputPipe = [NSPipe pipe];
    [task setStandardOutput:outputPipe];
    [task setStandardError:outputPipe];

    NSFileHandle *fileHandle = [outputPipe fileHandleForReading];

    // If system-wide, use sudo
    if (systemWide) {
        NSAppleScript *appleScript = [[NSAppleScript alloc] initWithSource:
            [NSString stringWithFormat:@"do shell script \"/bin/bash %@\" with administrator privileges", scriptPath]];

        NSDictionary *errorDict = nil;
        [appleScript executeAndReturnError:&errorDict];

        if (errorDict) {
            dispatch_async(dispatch_get_main_queue(), ^{
                [self showError:@"Installation cancelled or failed. Please try again."];
            });
            return;
        }
    } else {
        [task launch];
        [task waitUntilExit];

        if ([task terminationStatus] != 0) {
            NSData *outputData = [fileHandle readDataToEndOfFile];
            NSString *output = [[NSString alloc] initWithData:outputData encoding:NSUTF8StringEncoding];

            dispatch_async(dispatch_get_main_queue(), ^{
                [self showError:[NSString stringWithFormat:@"Installation failed:\n%@", output]];
            });
            return;
        }
    }

    // Success!
    dispatch_async(dispatch_get_main_queue(), ^{
        [self.progressIndicator stopAnimation:nil];
        [self.progressIndicator setHidden:YES];
        [self.statusLabel setStringValue:@"Installation complete!"];
        [self.statusLabel setTextColor:[NSColor systemGreenColor]];

        NSAlert *alert = [[NSAlert alloc] init];
        [alert setMessageText:@"Installation Complete"];
        [alert setInformativeText:@"Shaw Spell has been installed successfully!\n\n"
            @"Next steps:\n"
            @"1. Restart Dictionary.app to use the dictionaries\n"
            @"2. The spell server is now running\n"
            @"3. Configure spell-checking in:\n"
            @"   System Settings > Keyboard > Text Input > Edit...\n"
            @"   Look for 'ShawDict' in the spell checker list"];
        [alert setAlertStyle:NSAlertStyleInformational];
        [alert addButtonWithTitle:@"OK"];
        [alert runModal];

        [[NSApplication sharedApplication] terminate:nil];
    });
}

- (void)showError:(NSString *)message {
    [self.progressIndicator stopAnimation:nil];
    [self.progressIndicator setHidden:YES];
    [self.statusLabel setStringValue:@"Installation failed"];
    [self.statusLabel setTextColor:[NSColor systemRedColor]];
    [self.installButton setEnabled:YES];

    NSAlert *alert = [[NSAlert alloc] init];
    [alert setMessageText:@"Installation Error"];
    [alert setInformativeText:message];
    [alert setAlertStyle:NSAlertStyleCritical];
    [alert addButtonWithTitle:@"OK"];
    [alert runModal];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
    return YES;
}

@end

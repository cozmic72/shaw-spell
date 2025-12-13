//
//  InstallerAppDelegate.h
//  Shaw Spell Installer
//
//  Main application delegate for the installer.
//

#import <Cocoa/Cocoa.h>

@interface InstallerAppDelegate : NSObject <NSApplicationDelegate>

@property (strong, nonatomic) NSWindow *window;
@property (strong, nonatomic) NSButton *installButton;
@property (strong, nonatomic) NSProgressIndicator *progressIndicator;
@property (strong, nonatomic) NSTextField *statusLabel;
@property (strong, nonatomic) NSButton *dialectGBCheckbox;
@property (strong, nonatomic) NSButton *dialectUSCheckbox;
@property (strong, nonatomic) NSButton *systemWideCheckbox;
@property (strong, nonatomic) NSTextView *instructionsView;

- (void)installButtonClicked:(id)sender;
- (void)performInstallation;

@end

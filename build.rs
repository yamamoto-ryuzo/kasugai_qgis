use std::io;

fn main() -> io::Result<()> {
    #[cfg(windows)]
    {
        use winres::WindowsResource;
        WindowsResource::new()
            .set_icon("installer/app_icon.ico")
            .compile()?;
    }
    Ok(())
}

use std::io;

fn main() -> io::Result<()> {
    // include_str! 用 HTML の変更を検知し、再ビルドを促す
    println!("cargo:rerun-if-changed=public/index.html");

    #[cfg(windows)]
    {
        use winres::WindowsResource;
        WindowsResource::new()
            .set_icon("installer/app_icon.ico")
            .compile()?;
    }
    Ok(())
}

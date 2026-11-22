plugins { java }

version = "0.1.0"
repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}
val paperApi = providers.gradleProperty("paperApi").orElse("1.21.5-R0.1-SNAPSHOT")
dependencies {
    compileOnly("io.papermc.paper:paper-api:${paperApi.get()}")
    testImplementation("org.mockbukkit.mockbukkit:mockbukkit-v1.21:v4.52.1")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}
tasks.test { useJUnitPlatform() }
tasks.withType<JavaCompile>().configureEach {
    options.release.set(21)
    options.encoding = "UTF-8"
}

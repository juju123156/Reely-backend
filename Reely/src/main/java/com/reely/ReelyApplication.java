package com.reely;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.SecurityAutoConfiguration;

// 스프링 시큐리티 임시로 막아둠
@SpringBootApplication(exclude = SecurityAutoConfiguration.class)
public class ReelyApplication {

	public static void main(String[] args) {
		SpringApplication.run(ReelyApplication.class, args);
	}

}

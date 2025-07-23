package com.reely.config;

import org.apache.ibatis.session.SqlSessionFactory;
import org.mybatis.spring.SqlSessionTemplate;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.PlatformTransactionManager;
import javax.sql.DataSource;

@Configuration
@MapperScan("com.reely.mapper") // Mapper 인터페이스가 위치한 패키지
public class MyBatisConfig {

    // DataSource를 자동으로 설정하기 위해 Spring Boot의 DataSource 빈을 사용합니다.
    private final DataSource dataSource;

    public MyBatisConfig(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Bean
    public SqlSessionFactory sqlSessionFactory() throws Exception {
        org.mybatis.spring.SqlSessionFactoryBean sessionFactoryBean = new org.mybatis.spring.SqlSessionFactoryBean();
        sessionFactoryBean.setDataSource(dataSource);

        // MyBatis 설정 파일(mybatis-config.xml)을 지정할 수 있습니다.
        sessionFactoryBean.setConfigLocation(new org.springframework.core.io.ClassPathResource("mybatis-config.xml"));
        
        return sessionFactoryBean.getObject();
    }

    @Bean
    public SqlSessionTemplate sqlSessionTemplate(SqlSessionFactory sqlSessionFactory) {
        return new SqlSessionTemplate(sqlSessionFactory);
    }

    @Bean
    public PlatformTransactionManager transactionManager() {
        return new DataSourceTransactionManager(dataSource);
    }
}

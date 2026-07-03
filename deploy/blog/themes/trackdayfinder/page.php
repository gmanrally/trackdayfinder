<?php if ( ! defined( 'ABSPATH' ) ) exit; get_header(); ?>

<?php while ( have_posts() ) : the_post(); ?>
	<article class="tdf-page" id="page-<?php the_ID(); ?>">
		<h1 style="margin-top:0"><?php the_title(); ?></h1>

		<?php if ( has_post_thumbnail() ) : ?>
			<div style="margin:0 0 18px">
				<?php the_post_thumbnail( 'large', array( 'style' => 'width:100%;height:auto;border-radius:6px;border:1px solid var(--line)' ) ); ?>
			</div>
		<?php endif; ?>

		<div class="tdf-content">
			<?php the_content(); ?>
			<?php wp_link_pages( array( 'before' => '<p>Pages: ', 'after' => '</p>' ) ); ?>
		</div>
	</article>

	<?php if ( comments_open() || get_comments_number() ) : ?>
		<div class="tdf-page" style="margin-top:18px">
			<?php comments_template(); ?>
		</div>
	<?php endif; ?>

<?php endwhile; ?>

<?php get_footer(); ?>
